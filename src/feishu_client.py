import time
import requests
from typing import List, Dict, Any
from src.models import SalesRecord
import src.config as config
from src.utils import logger, network_retry_decorator

class FeishuClient:
    """
    飞书 (Lark) API 客户端。支持真实的飞书开放平台接口，以及本地仿真/模拟器模式。
    包含 Tenant Token 自动缓存、限流指数退避重试、多维表格数据拉取和群机器人 Webhook 推送。
    """
    def __init__(self):
        self.app_id = config.FEISHU_APP_ID
        self.app_secret = config.FEISHU_APP_SECRET
        self.token_cache = {
            "token": "",
            "expire_at": 0
        }
        
    @network_retry_decorator
    def _get_tenant_access_token_api(self) -> str:
        """
        内部 API 调用：获取 tenant_access_token，已挂载 Tenacity 自动重试。
        """
        logger.info("[飞书客户端] 正在请求新的 tenant_access_token...")
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        # 抛出 HTTP 状态错误（429 限流或 5xx 服务不可用时，Tenacity 将自动捕获并执行退避重试）
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") != 0:
            raise ValueError(f"获取飞书 Token 失败: {data.get('msg')}")
            
        return data["tenant_access_token"], data["expire"]

    def _get_tenant_access_token(self) -> str:
        """
        获取 tenant_access_token 并支持在内存中自动进行有效期缓存（设定 60 秒的缓冲失效期）。
        """
        if self.token_cache["token"] and self.token_cache["expire_at"] > time.time() + 60:
            return self.token_cache["token"]
            
        token, expire = self._get_tenant_access_token_api()
        
        self.token_cache = {
            "token": token,
            "expire_at": time.time() + expire
        }
        return token

    @network_retry_decorator
    def _fetch_records_page(self, url: str, headers: Dict[str, str], params: Dict[str, Any]) -> Dict[str, Any]:
        """
        内部 API 调用：单页拉取多维表格数据，已挂载 Tenacity 自动重试。
        """
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    def fetch_bitable_records(self, app_token: str = None, table_id: str = None) -> List[SalesRecord]:
        """
        从飞书多维表格中拉取所有记录。
        如果 config.USE_FEISHU_SIMULATION 为 True，则自动切换为仿真模拟器模式，返回当天模拟交易数据。
        """
        if config.USE_FEISHU_SIMULATION:
            return self._simulate_bitable_records()
            
        app_token = app_token or config.FEISHU_BITABLE_APP_TOKEN
        table_id = table_id or config.FEISHU_BITABLE_TABLE_ID
        
        if not app_token or not table_id:
            raise ValueError("禁用仿真模式时，必须配置多维表格的 app_token 和 table_id。")
            
        token = self._get_tenant_access_token()
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8"
        }
        
        records = []
        page_token = ""
        has_more = True
        
        while has_more:
            params = {"page_size": 100}
            if page_token:
                params["page_token"] = page_token
                
            res_data = self._fetch_records_page(url, headers, params)
            
            if res_data.get("code") != 0:
                raise ValueError(f"拉取多维表格记录失败: {res_data.get('msg')}")
                
            data = res_data.get("data", {})
            items = data.get("items", [])
            
            for item in items:
                fields = item.get("fields", {})
                record_id = item.get("record_id", "")
                
                # 兼容处理字段名为中文或英文的情况，实现稳健的动态映射
                salesperson = fields.get("Salesperson", fields.get("销售人员", fields.get("salesperson", "")))
                product = fields.get("Product", fields.get("产品名称", fields.get("product", "")))
                amount = fields.get("Amount", fields.get("销售金额", fields.get("amount", 0.0)))
                customer = fields.get("Customer", fields.get("客户名称", fields.get("customer", "")))
                date = fields.get("Date", fields.get("交易日期", fields.get("date", "")))
                
                # 多维表格可能返回毫秒级时间戳，需自动格式化为 YYYY-MM-DD
                if isinstance(date, int):
                    date = time.strftime('%Y-%m-%d', time.localtime(date / 1000))
                
                records.append(SalesRecord(
                    record_id=str(record_id),
                    salesperson=str(salesperson),
                    product=str(product),
                    amount=float(amount),
                    customer=str(customer),
                    date=str(date)
                ))
                
            has_more = data.get("has_more", False)
            page_token = data.get("page_token", "")
            
        logger.info(f"[飞书客户端] 成功拉取多维表格记录。共 {len(records)} 条。")
        return records

    @network_retry_decorator
    def _push_webhook_api(self, webhook_url: str, payload: Dict[str, Any]):
        """
        内部 API 调用：推送消息卡片至群 Webhook，已挂载 Tenacity 自动重试。
        """
        headers = {"Content-Type": "application/json; charset=utf-8"}
        response = requests.post(webhook_url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def push_to_group_webhook(self, message_card: Dict[str, Any], webhook_url: str = None) -> bool:
        """
        通过自定义群机器人的 Webhook 推送交互式消息卡片。
        """
        webhook_url = webhook_url or config.FEISHU_WEBHOOK_URL
        if not webhook_url:
            logger.info("[飞书客户端] (仿真调试) 未配置 Webhook URL。本地模拟打印消息卡片内容:")
            import json
            try:
                print(json.dumps(message_card, indent=2, ensure_ascii=False))
            except UnicodeEncodeError:
                print(json.dumps(message_card, indent=2, ensure_ascii=True))
            return True
            
        payload = {
            "msg_type": "interactive",
            "card": message_card
        }
        
        res_data = self._push_webhook_api(webhook_url, payload)
        
        if res_data.get("code") != 0:
            raise ValueError(f"群 Webhook 推送失败: {res_data.get('msg')}")
            
        logger.info("[飞书客户端] 交互式消息卡片已成功推送到飞书群聊。")
        return True

    def _simulate_bitable_records(self) -> List[SalesRecord]:
        """
        (仿真模式数据源) 生成逼真的销售记录数据。
        """
        today_str = time.strftime('%Y-%m-%d', time.localtime())
        logger.info(f"[飞书客户端仿真模式] 正在生成今日销售数据模拟 {today_str}...")
        return [
            SalesRecord(record_id="rec001", salesperson="王亮", product="AI企业级智能体助手", amount=45000.00, customer="阿里达摩院", date=today_str),
            SalesRecord(record_id="rec002", salesperson="李梅", product="企业RAG私有知识库", amount=28000.00, customer="南方电网", date=today_str),
            SalesRecord(record_id="rec003", salesperson="王亮", product="数字人短视频生成系统", amount=15000.00, customer="新东方甄选", date=today_str),
            SalesRecord(record_id="rec004", salesperson="张伟", product="AI企业级智能体助手", amount=45000.00, customer="极客邦科技", date=today_str),
            SalesRecord(record_id="rec005", salesperson="李梅", product="大模型定制微调服务", amount=62000.00, customer="顺丰速运", date=today_str),
        ]
