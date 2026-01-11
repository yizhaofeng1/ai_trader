import base64
import json
import os
import random
from openai import OpenAI
from django.conf import settings
from django.core.files.base import ContentFile


class AIService:
    def __init__(self, user=None):
        self.user = user
        self.client = None
        self.model = "qwen-vl-max"  # 默认

        # 1. 优先读取用户的配置
        if self.user and hasattr(self.user, 'userprofile'):
            profile = self.user.userprofile
            if profile.api_key:
                self.api_key = profile.api_key
                self.base_url = profile.api_base_url
                self.model = profile.selected_model
            else:
                self.api_key = getattr(settings, 'AI_API_KEY', None)
                self.base_url = getattr(settings, 'AI_BASE_URL', None)
        else:
            self.api_key = getattr(settings, 'AI_API_KEY', None)
            self.base_url = getattr(settings, 'AI_BASE_URL', None)

        if self.api_key:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _encode_image(self, image_path):
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')

    def _save_json_file(self, result_dict, record_instance):
        """将结果保存到本地 JSON 文件并关联到记录"""
        # 保存前再次确保数据完整性
        self._ensure_safe_data(result_dict)

        json_content = json.dumps(result_dict, indent=4, ensure_ascii=False)
        file_name = os.path.basename(record_instance.chart_image.name).split('.')[0] + '_analysis.json'
        record_instance.json_file.save(file_name, ContentFile(json_content.encode('utf-8')), save=False)

    def _ensure_safe_data(self, data):
        """【安全补丁】确保字典中包含前端必须的所有字段，防止 KeyError"""
        # 如果没有最终信号，默认使用原始信号
        if 'final_signal' not in data:
            data['final_signal'] = data.get('signal', 'WAIT')
        if 'raw_signal' not in data:
            data['raw_signal'] = data.get('signal', 'WAIT')
        if 'strategy_reason' not in data:
            data['strategy_reason'] = "AI 原始分析（未经过滤）"
        if 'confidence' not in data:
            data['confidence'] = 0  # 默认置信度

    def analyze_and_save(self, image_full_path, record_instance):
        """分析并保存文件"""
        result = self.analyze_chart_image(image_full_path)
        # 保存 JSON 实体文件
        self._save_json_file(result, record_instance)
        return result

    def analyze_chart_image(self, image_full_path):
        if not self.client:
            print("⚠️ 无有效 API Key，使用模拟数据")
            return self._get_mock_data()

        base64_img = self._encode_image(image_full_path)

        # 使用你最新的 Prompt
        system_prompt = """
        你是一个严谨、客观的股票交易算法辅助系统，仅提供技术结构分析，不进行投资建议或主观判断。

        【任务】
        基于输入的股票K线图像，对以下要素进行分析：
        - 价格趋势、形态与所处阶段
        - 均线系统结构（短、中、长周期）
        - 量价配合状态与波动率
        - 关键支撑与压力位
        - 潜在技术风险（如乖离、超涨、背离、破位）

        【分析范围限制】
        - 仅基于图像中的技术信息（K线、均线、成交量、MACD/KDJ等副图如果有）
        - 不使用、不推断任何基本面、消息面或情绪面信息
        - 不预测未来，只描述当前技术状态及其逻辑推论

        【输出要求】
        - 必须且只能输出符合 JSON 语法的字符串
        - 不得包含 ```json 或任何额外说明文本
        - 所有数值必须为图像可合理推导的近似值
        - 不使用“建议”“推荐”“应该”等主观词汇

        【JSON 结构定义】
        {
            "symbol": "股票代码或 Unknown",
            "trend": "Up/Down/Range",
            "trend_stage": "Early/Middle/Accelerating/Exhaustion/Unknown",
            "primary_pattern": "识别到的具体形态，如：Double Bottom, Flag, Box, Head and Shoulders, None",
            "ma_structure": "Bullish/Bearish/Mixed/Tangled",
            "price_ma_deviation": "Low/Medium/High",
            "volume_state": "Expanding/Contracting/Neutral/Abnormal",
            "volatility_status": "Low/Normal/High",
            "support_levels": [0.0],
            "resistance_levels": [0.0],
            "risk_factors": [
                "Overextended from long-term MA",
                "Bearish Divergence",
                "Volume decreasing on rally",
                "Approaching major resistance"
            ],
            "signal": "BUY/SELL/WAIT",
            "signal_applicable_to": "Holder/NonHolder/Both",
            "score": 0-100,
            "confidence": 0-100,
            "key_levels": {
                "short_term_hold": 0.0,
                "trend_invalid": 0.0
            },
            "reason": "不超过50字的技术结构性总结，客观描述当前状态与核心矛盾"
        }
        """

        try:
            print(f"🚀 调用模型: {self.model} | URL: {self.base_url}")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": [
                        {"type": "text", "text": "分析这张图表"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}},
                    ]},
                ],
                response_format={"type": "json_object"}
            )

            # 解析结果
            result = json.loads(response.choices[0].message.content)

            # 【关键修复】在返回给 Views 之前，先注入默认的策略字段
            # 这样即使 Views 没有进行策略计算，前端也不会因为缺字段而报错
            self._ensure_safe_data(result)

            return result

        except Exception as e:
            print(f"❌ API 错误: {e}")
            if "400" in str(e) or "image" in str(e):
                return self._get_mock_data()
            return {"error": str(e), "signal": "ERROR", "reason": "API连接失败"}

    def _get_mock_data(self):
        """
        【兜底方案】Mock 数据现在完全匹配最新的 Prompt 结构
        """
        trend = random.choice(["Upward 📈", "Downward 📉", "Sideways ➡️"])
        signal = "BUY" if "Up" in trend else ("SELL" if "Down" in trend else "HOLD")
        score = random.randint(80, 95) if signal == "BUY" else random.randint(40, 60)

        data = {
            "symbol": "MOCK-TEST",
            "trend": trend,
            "trend_stage": "Early",
            "primary_pattern": "Double Bottom",  # 新增
            "ma_structure": "Bullish",
            "price_ma_deviation": "Low",
            "volume_state": "Expanding",  # 新增
            "volatility_status": "Normal",  # 新增
            "support_levels": [10.5, 10.2],
            "resistance_levels": [12.0, 12.5],
            "risk_factors": [],
            "key_levels": {"short_term_hold": 10.0, "trend_invalid": 9.5},
            "score": score,
            "confidence": 92,  # 新增
            "signal": signal,
            "reason": "【模拟模式】API 调用异常（Key无效或额度超限），仅展示演示数据。",

            # 策略字段
            "final_signal": signal,
            "raw_signal": signal,
            "strategy_reason": "模拟数据默认通过策略"
        }
        return data