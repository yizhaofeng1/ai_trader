import json
import re
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from openai import OpenAI  # 用于测试连接获取模型

from .models import AnalysisRecord, UserProfile
from .forms import ImageUploadForm
from .services import AIService
from .strategy_engine import StrategyEngine
from .gtja_api import GTJAClient
def dashboard(request):
    """主界面视图：支持上传分析 和 历史回看"""
    result_data = None
    latest_record = None
    form = ImageUploadForm()
    history = []

    # 1. 基础权限检查
    if request.user.is_authenticated:
        # 获取该用户的所有历史记录
        history = AnalysisRecord.objects.filter(user=request.user).order_by('-created_at')[:20]  # 显示最近20条

        # === 核心修改 A: 处理历史记录回看 (GET 请求带 view_id) ===
        view_id = request.GET.get('view_id')
        if view_id:
            try:
                # 获取指定的记录 (必须是当前用户的，防止越权查看)
                record_obj = AnalysisRecord.objects.get(pk=view_id, user=request.user)

                # 读取关联的 JSON 文件
                if record_obj.json_file:
                    try:
                        # 【修正点】使用 'rb' (二进制) 模式打开，然后手动 decode('utf-8')
                        record_obj.json_file.open('rb')
                        file_content = record_obj.json_file.read()
                        record_obj.json_file.close()  # 记得关闭文件句柄

                        # 将二进制数据解码为字符串，再解析 JSON
                        result_data = json.loads(file_content.decode('utf-8'))

                        latest_record = record_obj  # 将其设为当前显示的记录
                    except Exception as e:
                        print(f"读取 JSON 文件失败: {e}")
                        # 如果读取文件失败，尝试读数据库备份字段作为兜底
                        result_data = record_obj.ai_result
                        latest_record = record_obj
                else:
                    # 如果没有文件 (旧数据兼容)，尝试读取数据库中的备份字段
                    result_data = record_obj.ai_result
                    latest_record = record_obj

            except AnalysisRecord.DoesNotExist:
                print("记录不存在或无权访问")

        # === 处理新上传 (POST 请求) ===
        if request.method == 'POST' and request.FILES.get('chart_image'):
            form = ImageUploadForm(request.POST, request.FILES)
            if form.is_valid():
                record = form.save(commit=False)
                record.user = request.user
                record.save()

                ai_service = AIService(user=request.user)

                try:
                    # 1. AI 分析
                    analysis_result = ai_service.analyze_and_save(record.chart_image.path, record)

                    # 2. === 策略引擎介入 ===
                    engine = StrategyEngine(request.user)
                    final_sig, reason = engine.evaluate(analysis_result)

                    # 3. 保存结果
                    record.ai_result = analysis_result
                    record.raw_signal = analysis_result.get('signal', 'N/A')  # AI 原始
                    record.final_signal = final_sig  # 策略最终
                    record.strategy_reason = reason  # 判定理由
                    record.save()

                    # 把策略结果也塞进 result_data 传给前端显示
                    result_data = analysis_result
                    result_data['final_signal'] = final_sig
                    result_data['strategy_reason'] = reason

                    latest_record = record
                except Exception as e:
                    # 错误处理
                    result_data = {"error": str(e), "signal": "ERROR", "reason": "分析过程出错"}

    return render(request, 'scanner/dashboard.html', {
        'form': form,
        'result': result_data,
        'record': latest_record,
        'history': history,
        'user': request.user
    })

# === 用户认证 API (AJAX) ===
@csrf_exempt
def api_login(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        user = authenticate(username=data.get('username'), password=data.get('password'))
        if user:
            login(request, user)
            return JsonResponse({'status': 'success'})
        return JsonResponse({'status': 'error', 'message': '用户名或密码错误'})


@csrf_exempt
def api_register(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        username = data.get('username')
        password = data.get('password')
        question = data.get('security_question')
        answer = data.get('security_answer')

        if not re.match(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,}$', password):
            return JsonResponse({'status': 'error', 'message': '密码必须包含字母和数字，且至少6位'})

        if User.objects.filter(username=username).exists():
            return JsonResponse({'status': 'error', 'message': '用户名已存在'})

        user = User.objects.create_user(username=username, password=password)
        profile = user.userprofile
        profile.security_question = question
        profile.security_answer = answer
        profile.save()

        login(request, user)
        return JsonResponse({'status': 'success'})


@csrf_exempt
def api_reset_password(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        try:
            user = User.objects.get(username=data.get('username'))
            profile = user.userprofile
            if profile.security_question == data.get('question') and profile.security_answer == data.get('answer'):
                new_pass = data.get('new_password')
                if not re.match(r'^(?=.*[A-Za-z])(?=.*\d)[A-Za-z\d]{6,}$', new_pass):
                    return JsonResponse({'status': 'error', 'message': '新密码格式不正确'})

                user.set_password(new_pass)
                user.save()
                login(request, user)
                return JsonResponse({'status': 'success'})
            else:
                return JsonResponse({'status': 'error', 'message': '密保答案错误'})
        except User.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': '用户不存在'})


@login_required
def api_logout(request):
    logout(request)
    return JsonResponse({'status': 'success'})


@login_required
@csrf_exempt
def fetch_external_models(request):
    """筛选视觉模型"""
    if request.method == 'POST':
        data = json.loads(request.body)
        api_key = data.get('api_key')
        base_url = data.get('base_url')

        VISION_KEYWORDS = ['vl', 'vision', 'gpt-4o', 'omni', 'gemini', 'claude-3', 'llava']

        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            models_list = client.models.list()
            vision_models = []
            all_models = []

            for m in models_list.data:
                model_id = m.id
                all_models.append(model_id)
                if any(keyword in model_id.lower() for keyword in VISION_KEYWORDS):
                    vision_models.append(model_id)

            if vision_models:
                vision_models.sort()
                return JsonResponse({'status': 'success', 'models': vision_models,
                                     'message': f'成功筛选出 {len(vision_models)} 个支持视觉分析的模型'})
            else:
                all_models.sort()
                return JsonResponse(
                    {'status': 'success', 'models': all_models, 'message': '未检测到标准命名的视觉模型，已显示全部模型'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})


@login_required
@csrf_exempt
def save_settings(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        profile = request.user.userprofile
        profile.api_key = data.get('api_key')
        profile.api_base_url = data.get('base_url')
        profile.selected_model = data.get('model')
        profile.save()
        return JsonResponse({'status': 'success'})


@login_required
@csrf_exempt
def save_strategy_config(request):
    """保存策略配置 (已升级支持置信度和波动率)"""
    if request.method == 'POST':
        data = json.loads(request.body)
        config = request.user.strategyconfig

        # 原有字段
        config.min_score_buy = int(data.get('min_score', 75))
        config.require_bullish_ma = data.get('require_bullish', False)
        config.max_risk_factors = int(data.get('max_risks', 1))
        config.allow_sideways = data.get('allow_sideways', False)

        # === 新增字段保存 ===
        config.min_confidence = int(data.get('min_confidence', 60))
        config.allow_high_volatility = data.get('allow_high_volatility', False)

        config.save()
        return JsonResponse({'status': 'success'})


@login_required
def delete_record(request, pk):
    if request.method == 'POST':
        record = get_object_or_404(AnalysisRecord, pk=pk, user=request.user)
        record.delete()
    return redirect('dashboard')


from .models import VirtualAccount, PaperOrder
from decimal import Decimal


@login_required
def trade_ticket_view(request, record_id):
    """渲染交易票据页面 (The New Interface)"""
    record = get_object_or_404(AnalysisRecord, pk=record_id, user=request.user)

    # 读取 AI 分析结果用于预填充
    ai_data = {}
    if record.json_file:
        try:
            record.json_file.open('rb')
            ai_data = json.loads(record.json_file.read().decode('utf-8'))
        except:
            ai_data = record.ai_result or {}
    else:
        ai_data = record.ai_result or {}

    # 获取用户账户信息
    account, _ = VirtualAccount.objects.get_or_create(user=request.user)

    # 提取 AI 推荐值
    symbol = ai_data.get('symbol', 'UNKNOWN')

    # 智能提取价格：模拟当前价（实际应从行情API获取，这里暂时假设可以手动填）
    # 智能提取止损：取 key_levels.trend_invalid 或 support_levels[0]
    stop_loss_rec = 0
    key_levels = ai_data.get('key_levels', {})
    supports = ai_data.get('support_levels', [])
    if key_levels.get('trend_invalid'):
        stop_loss_rec = key_levels['trend_invalid']
    elif supports:
        stop_loss_rec = supports[0]

    # 智能提取止盈：取 resistance_levels[0]
    take_profit_rec = 0
    resistances = ai_data.get('resistance_levels', [])
    if resistances:
        take_profit_rec = resistances[0]

    context = {
        'record': record,
        'ai_data': ai_data,
        'account': account,
        'symbol': symbol,
        'rec_sl': stop_loss_rec,
        'rec_tp': take_profit_rec,
        'final_signal': getattr(record, 'final_signal', 'WAIT')
    }
    return render(request, 'scanner/trade_ticket.html', context)


@login_required
@csrf_exempt
def execute_paper_order(request):
    """执行订单 (支持 模拟盘 和 实盘)"""
    if request.method == 'POST':
        data = json.loads(request.body)
        user = request.user
        account = user.virtualaccount  # 获取账户

        symbol = data.get('symbol')
        price = Decimal(data.get('price'))
        qty = int(data.get('quantity'))
        direction = "BUY"  # 默认买入

        # === 分支逻辑 ===
        if not account.is_simulation:
            # >>>>> 进入实盘模式 <<<<<
            if not (account.broker_app_id and account.broker_app_secret):
                return JsonResponse({'status': 'error', 'message': '实盘交易失败：未配置 GTJA API 密钥'})

            try:
                # 初始化客户端
                client = GTJAClient(
                    app_id=account.broker_app_id,
                    app_secret=account.broker_app_secret,
                    customer_id=account.broker_customer_id
                )

                # 发送真实请求
                result = client.place_order(symbol, price, qty, direction)

                if "error" in result:
                    return JsonResponse({'status': 'error', 'message': f"券商拒单: {result.get('message')}"})

                # 记录实盘订单 (建议新建一个 RealOrder 模型，或者在 PaperOrder 加个标记)
                PaperOrder.objects.create(
                    user=user,
                    symbol=symbol,
                    quantity=qty,
                    price=price,
                    status='FILLED',  # 需根据 API 返回状态更新
                    commission=0,  # 实盘佣金需查交割单
                    analysis_record_id=data.get('record_id')
                )

                return JsonResponse({'status': 'success', 'message': f'实盘委托成功！合同号: {result.get("order_id")}'})

            except Exception as e:
                return JsonResponse({'status': 'error', 'message': f'实盘接口异常: {str(e)}'})

        else:
            # >>>>> 保持原有的模拟盘逻辑 <<<<<
            total_cost = price * qty
            if account.balance < total_cost:
                return JsonResponse({'status': 'error', 'message': f'模拟资金不足！可用: {account.balance}'})

            account.balance -= total_cost
            account.save()

            PaperOrder.objects.create(
                user=user,
                analysis_record_id=data.get('record_id'),
                symbol=symbol,
                quantity=qty,
                price=price,
                status='FILLED'
            )

            return JsonResponse({'status': 'success', 'new_balance': str(account.balance)})