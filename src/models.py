from pydantic import BaseModel, Field
from typing import List, Optional

# --- 原始数据模型 ---

class SalesRecord(BaseModel):
    record_id: str = Field(description="多维表格中每条记录的唯一标识符")
    salesperson: str = Field(description="销售人员姓名")
    product: str = Field(description="售出产品名称")
    amount: float = Field(description="交易金额（支持人民币或美元）")
    customer: str = Field(description="客户公司或个人名称")
    date: str = Field(description="交易日期，格式为 YYYY-MM-DD")

# --- 结构化报表输出模型（大模型解析与校验的靶标 Schema） ---

class SalespersonHighlight(BaseModel):
    salesperson: str = Field(description="销售人员姓名")
    total_amount: float = Field(description="该销售人员今日成交的总金额")
    deal_count: int = Field(description="该销售人员今日关闭的订单总数")

class ProductPerformance(BaseModel):
    product: str = Field(description="产品名称")
    units_sold: int = Field(description="该产品售出的总件数")
    revenue: float = Field(description="该产品产生的总营业收入")

class DailyReport(BaseModel):
    report_date: str = Field(description="报表统计日期，格式为 YYYY-MM-DD")
    total_sales_amount: float = Field(description="今日所有交易记录的销售总金额")
    total_deals_count: int = Field(description="今日关闭的交易订单总件数")
    salesperson_highlights: List[SalespersonHighlight] = Field(description="按销售人员分组聚合的业绩明细")
    product_performance: List[ProductPerformance] = Field(description="按产品类别分组聚合的销量与营收明细")
    anomalies: List[str] = Field(description="异常监控警报（例如：核心产品零销售、单笔金额异常大或小、出现负值或退款等）")
    trend_analysis: str = Field(description="由大模型生成的趋势深度解读（比如：相比昨天的增长点归纳、业绩驱动主因等语义描述）")
