from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
import os


# 1. 用户扩展配置表 (存储 API Key 和 Base URL)
class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    security_question = models.CharField(max_length=100, help_text="密保问题：你的宠物叫什么？")
    security_answer = models.CharField(max_length=100)

    # API 配置
    api_key = models.CharField(max_length=200, blank=True, null=True)
    api_base_url = models.CharField(max_length=200, default="https://dashscope.aliyuncs.com/compatible-mode/v1")
    selected_model = models.CharField(max_length=100, default="qwen-vl-max")

    def __str__(self):
        return self.user.username


# === 新增：用户策略配置表 ===
class StrategyConfig(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # === 原有字段 ===
    min_score_buy = models.IntegerField(default=75, verbose_name="买入最低评分")
    require_bullish_ma = models.BooleanField(default=True, verbose_name="必须均线多头")
    max_risk_factors = models.IntegerField(default=1, verbose_name="允许最大风险因子数")
    allow_sideways = models.BooleanField(default=False, verbose_name="允许震荡趋势")

    # === 【新增字段】 ===
    min_confidence = models.IntegerField(default=60, verbose_name="最低AI置信度")
    # 默认60分：防止图片稍微有点不清楚就被拒，但拦截掉完全瞎猜的情况

    allow_high_volatility = models.BooleanField(default=False, verbose_name="允许高波动率")

    # 默认False：新手通常不喜欢暴涨暴跌的行情，风险大

    def __str__(self):
        return f"{self.user.username} 的策略"

# 2. 修改分析记录表 (增加 User 关联和 JSON 文件路径)
class AnalysisRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    chart_image = models.ImageField(upload_to='charts/%Y/%m/%d/')  # 注意这里你之前的 upload_to 函数保持你的写法即可
    json_file = models.FileField(upload_to='charts/%Y/%m/%d/', null=True, blank=True)
    ai_result = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # === 新增字段：存储最终策略判定 ===
    raw_signal = models.CharField(max_length=10, blank=True, verbose_name="AI原始信号")  # AI 说的
    final_signal = models.CharField(max_length=10, blank=True, verbose_name="策略最终信号")  # 过滤后的
    strategy_reason = models.CharField(max_length=200, blank=True, verbose_name="策略判定理由")  # 为什么被拒/通过

    # 动态路径：按 username/date 存储
    def user_directory_path(instance, filename):
        username = instance.user.username if instance.user else 'guest'
        return f'charts/{username}/{filename}'

    chart_image = models.ImageField(upload_to=user_directory_path)

    # 存储对应的 JSON 分析报告文件
    json_file = models.FileField(upload_to=user_directory_path, null=True, blank=True)

    ai_result = models.JSONField(null=True, blank=True)  # 数据库存一份方便查询
    signal = models.CharField(max_length=10, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def delete(self, *args, **kwargs):
        # 删除时自动清理图片和JSON文件
        if self.chart_image:
            if os.path.isfile(self.chart_image.path):
                os.remove(self.chart_image.path)
        if self.json_file:
            if os.path.isfile(self.json_file.path):
                os.remove(self.json_file.path)
        super().delete(*args, **kwargs)


# 信号：创建 User 时自动创建 Profile
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)
        StrategyConfig.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.userprofile.save()
    if hasattr(instance, 'strategyconfig'):
        instance.strategyconfig.save()



# === 模拟交易系统 ===
class VirtualAccount(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=20, decimal_places=2, default=1000000.00, verbose_name="可用资金")
    total_assets = models.DecimalField(max_digits=20, decimal_places=2, default=1000000.00, verbose_name="总资产")

    # 预留真实券商配置字段
    broker_api_key = models.CharField(max_length=200, blank=True, null=True)
    broker_api_secret = models.CharField(max_length=200, blank=True, null=True)
    is_simulation = models.BooleanField(default=True, verbose_name="是否模拟盘")
    # 扩展字段：真实交易配置
    broker_app_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="GTJA AppID")
    broker_app_secret = models.CharField(max_length=200, blank=True, null=True, verbose_name="GTJA AppSecret")
    broker_customer_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="资金账号")

    def __str__(self):
        def __str__(self):
            mode = "模拟盘" if self.is_simulation else "实盘"
            return f"{self.user.username} - {mode} - 余额: {self.balance}"


class PaperOrder(models.Model):
    STATUS_CHOICES = [
        ('PENDING', '待成交'),
        ('FILLED', '已成交'),
        ('CANCELED', '已撤单'),
        ('REJECTED', '已拒绝'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    analysis_record = models.ForeignKey(AnalysisRecord, on_delete=models.SET_NULL, null=True, blank=True)

    symbol = models.CharField(max_length=20)
    direction = models.CharField(max_length=10, default="BUY")  # BUY/SELL
    quantity = models.IntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)  # 成交均价/委托价

    # 策略参数
    stop_loss = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    take_profit = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='FILLED')  # 模拟盘默认直接成交
    commission = models.DecimalField(max_digits=10, decimal_places=2, default=5.0)  # 模拟手续费
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.symbol} {self.direction} @ {self.price}"


# 信号：创建用户时自动发钱
@receiver(post_save, sender=User)
def create_virtual_account(sender, instance, created, **kwargs):
    if created:
        VirtualAccount.objects.create(user=instance)