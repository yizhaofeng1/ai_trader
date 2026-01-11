# market_scanner/strategy_engine.py

class StrategyEngine:
    def __init__(self, user):
        self.user = user
        if hasattr(user, 'strategyconfig'):
            self.config = user.strategyconfig
        else:
            from .models import StrategyConfig
            self.config = StrategyConfig()

    def evaluate(self, ai_json):
        """
        输入: AI 分析的原始 JSON
        输出: (Final_Signal, Reason_String)
        """
        # 1. 提取 AI 数据 (增加 confidence 和 volatility 读取)
        ai_score = ai_json.get('score', 0)
        ai_signal = ai_json.get('signal', 'WAIT').upper()
        ai_trend = ai_json.get('trend', 'Unknown')
        ai_ma = ai_json.get('ma_structure', 'Mixed')
        risks = ai_json.get('risk_factors', [])

        # 新增提取
        ai_conf = ai_json.get('confidence', 0)
        ai_volatility = ai_json.get('volatility_status', 'Normal')

        # === 规则 0: AI 原始信号检查 ===
        if ai_signal != 'BUY':
            return ai_signal, "AI 原始信号非买入，策略保持一致"

        # === 【新增规则 A】: 置信度检查 (必须要先查这个，AI自己都不信就别往下看了) ===
        if ai_conf < self.config.min_confidence:
            return "WAIT", f"AI 置信度不足 ({ai_conf} < {self.config.min_confidence})，图像可能模糊或数据不足"

        # === 规则 1: 评分阈值检查 ===
        if ai_score < self.config.min_score_buy:
            return "WAIT", f"评分 {ai_score} 低于设定阈值 {self.config.min_score_buy}"

        # === 规则 2: 均线刚性要求 ===
        if self.config.require_bullish_ma:
            if "Bullish" not in ai_ma:
                return "WAIT", f"策略要求均线多头，当前为 {ai_ma}"

        # === 规则 3: 风险因子数量检查 ===
        if len(risks) > self.config.max_risk_factors:
            return "WAIT", f"风险因子数量 ({len(risks)}) 超过允许值 ({self.config.max_risk_factors})"

        # === 规则 4: 趋势过滤 ===
        if not self.config.allow_sideways:
            if "Range" in ai_trend or "Sideways" in ai_trend:
                return "WAIT", "策略已禁止震荡/盘整行情参与"

        # === 【新增规则 B】: 波动率风控 ===
        if not self.config.allow_high_volatility:
            if ai_volatility == "High":
                return "WAIT", "当前处于高波动状态(High Volatility)，策略已规避"

        # === 所有关卡通过 ===
        return "BUY", "✅ 符合所有策略阈值 (包括置信度与波动率)，确认执行"