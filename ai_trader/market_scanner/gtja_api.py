import time
import json
import hashlib
import requests
import logging

logger = logging.getLogger(__name__)


class GTJAClient:
    """
    国泰君安开放平台 API 客户端封装
    文档参考: https://open.gtja.com/door/v-index.html#/fileCenter
    """

    def __init__(self, app_id, app_secret, customer_id, api_base_url="https://open-api.gtja.com"):
        self.app_id = app_id
        self.app_secret = app_secret
        self.customer_id = customer_id
        self.base_url = api_base_url
        self.session = requests.Session()
        self.token = None

    def _sign(self, params):
        """
        生成签名 (SIGNATURE)
        注意：请根据 GTJA 官方文档的【签名算法】修改此函数
        通常涉及将参数排序、拼接 app_secret、然后做 MD5 或 SHA256
        """
        # 示例通用签名逻辑（请替换为官方逻辑）：
        sorted_params = sorted(params.items())
        sign_str = f"{self.app_secret}"
        for k, v in sorted_params:
            if k != "sign" and v:
                sign_str += f"{k}{v}"
        sign_str += f"{self.app_secret}"

        # 假设是 MD5
        return hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()

    def _request(self, method, endpoint, data=None):
        url = f"{self.base_url}{endpoint}"

        # 构造公共参数
        params = {
            "app_id": self.app_id,
            "timestamp": str(int(time.time() * 1000)),
            "version": "1.0",
            "format": "json",
            "customer_id": self.customer_id,  # 可能需要
        }

        if data:
            params.update(data)

        # 计算签名
        params["sign"] = self._sign(params)

        try:
            if method.upper() == "GET":
                response = self.session.get(url, params=params, timeout=5)
            else:
                # POST 请求通常传 JSON 或 Form Data，具体看文档 Content-Type 要求
                response = self.session.post(url, data=params, timeout=5)

            response.raise_for_status()
            result = response.json()

            # 检查业务状态码 (假设 0 或 '000000' 为成功)
            if str(result.get("code")) not in ["0", "000000", "success"]:
                raise Exception(f"GTJA API Error: {result.get('msg', 'Unknown Error')}")

            return result.get("data", result)

        except Exception as e:
            logger.error(f"Request failed: {e}")
            return {"status": "error", "message": str(e)}

    def place_order(self, symbol, price, quantity, direction):
        """
        下单接口
        :param direction: 'BUY' or 'SELL'
        """
        # 转换方向代码 (假设 1=买, 2=卖)
        trade_side = "1" if direction.upper() == "BUY" else "2"

        payload = {
            "stock_code": symbol,
            "price": str(price),
            "amount": str(quantity),
            "trade_direction": trade_side,
            "market": "SH" if symbol.startswith("6") else "SZ",  # 简单推断市场
            "order_type": "0"  # 限价委托
        }

        # 调用官方下单端点 (Endpoint 请查阅文档)
        return self._request("POST", "/api/trade/order/place", payload)

    def get_assets(self):
        """查询资产"""
        return self._request("GET", "/api/trade/assets/query")