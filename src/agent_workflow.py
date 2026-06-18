import json
import time
from typing import List, Dict, Any, Tuple
from openai import OpenAI
from src.models import SalesRecord, DailyReport, SalespersonHighlight, ProductPerformance
import src.config as config
from src.feishu_client import FeishuClient

class AgentWorkflow:
    """
    飞书每日销售看板 AI Agent 工作流。
    步骤：
      1. 拉取原始多维表格数据
      2. 校验数据完整性与判定空数据边界
      3. 调用大模型 (LLM) 生成结构化的 JSON 每日报表
      4. 通过 Python 代码强校验大模型返回的数值、求和公式与幻觉字段
      5. 反思自愈环路 (Reflection Loop)：若校验不通过，组装 Feedback 反传 LLM 进行修正 (上限 MAX_REFLECTION_ATTEMPTS)
      6. 渲染高大上的飞书群聊消息卡片
      7. 发送至飞书群机器人 Webhook
    """
    def __init__(self, feishu_client: FeishuClient = None):
        self.feishu = feishu_client or FeishuClient()
        if not config.USE_LLM_SIMULATION:
            self.llm_client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
        else:
            self.llm_client = None
            
    def run(self, simulate_hallucination: bool = False) -> Dict[str, Any]:
        """
        执行整个 Agent 工作流管道。
        """
        print("\n=== [Agent 工作流] 启动今日销售报表自动生成程序 ===")
        
        # 1. 抓取原始多维表格数据
        try:
            records = self.feishu.fetch_bitable_records()
        except Exception as e:
            print(f"[Agent 运行错误] 原始数据接入失败: {str(e)}")
            raise RuntimeError(f"数据摄入阶段崩溃: {str(e)}")
            
        # 2. 判断空数据边界条件（稳定性 Case 1）
        if not records:
            print("[Agent 工作流] 检测到今日无销售交易记录。启用空数据拦截模式，生成空状态警报。")
            empty_card = self._build_empty_state_card()
            self.feishu.push_to_group_webhook(empty_card)
            return {"status": "success", "message": "未发现今日销售记录", "report": None}
            
        # 3. 运行 LLM 提示词生成与反射自愈主流程
        report, logs = self._generate_and_verify_report(records, simulate_hallucination)
        
        # 4. 将结构化报表转化为高级飞书群聊卡片
        card = self._build_report_card(report)
        
        # 5. 推送卡片至飞书机器人
        self.feishu.push_to_group_webhook(card)
        
        return {
            "status": "success",
            "report": report.model_dump(),
            "reflection_logs": logs
        }
        
    def _generate_and_verify_report(self, records: List[SalesRecord], simulate_hallucination: bool) -> Tuple[DailyReport, List[Dict[str, Any]]]:
        """
        执行大模型结构化提取，并使用程序化数据 guardrails 进行合规校验。
        若发现数据计算错漏或幻觉，则自动触发反思自我纠错（Self-Correction）循环。
        """
        reflection_logs = []
        feedback = ""
        attempt = 1
        
        records_json = json.dumps([r.model_dump() for r in records], ensure_ascii=False, indent=2)
        
        while attempt <= config.MAX_REFLECTION_ATTEMPTS:
            print(f"\n[反思纠错环路] 正在运行第 {attempt} 次生成（最高限额: {config.MAX_REFLECTION_ATTEMPTS}）...")
            
            # 调用大语言模型 API（或仿真模拟器）
            raw_response = self._call_llm_api(records_json, feedback, attempt, simulate_hallucination)
            
            # 第一层校验：JSON 解析与 Pydantic 强类型规范化
            try:
                report_dict = self._extract_json_from_response(raw_response)
                report = DailyReport.model_validate(report_dict)
                parse_error = None
            except Exception as e:
                parse_error = f"JSON格式解析或 Schema 类型校验失败: {str(e)}。模型原始返回内容前 200 字: {raw_response[:200]}"
                report = None
                
            # 第二层校验：如果 JSON 解析成功，使用 Python 业务逻辑验证数值准确性（防幻觉/防错算）
            errors = []
            if parse_error:
                errors.append(parse_error)
            else:
                errors = self._validate_report_data(records, report)
                
            # 记录当前轮次的生成日志与报错细节
            log_entry = {
                "attempt": attempt,
                "raw_response": raw_response,
                "errors": errors.copy(),
                "status": "PASSED" if not errors else "FAILED"
            }
            reflection_logs.append(log_entry)
            
            # 校验通过，立即安全退出
            if not errors:
                print(f"[反思纠错环路] 验证成功！报表数据在第 {attempt} 次生成中通过全部强校验。")
                return report, reflection_logs
                
            # 校验未通过，整合报错 Trace，自动构造反思 Prompt 并重试
            print(f"[反思纠错环路] 验证失败！数据 guardrail 阻断了 {len(errors)} 个合规问题：")
            for err in errors:
                print(f"  - {err}")
                
            feedback = "The previous output failed guardrail validation. Please correct the following errors:\n"
            for i, err in enumerate(errors, 1):
                feedback += f"{i}. {err}\n"
            feedback += "Ensure all figures sum up perfectly and that you do not invent any fields, names, or values."
            
            attempt += 1
            # 一旦第一轮完成，如果是模拟模式，则关闭模拟幻觉开关，使其在第二轮能自愈生成正确数据
            if simulate_hallucination:
                simulate_hallucination = False
                
        # 第三层灾备：如果达到反思最大迭代上限大模型仍未算对，采用本地 Python 程序化计算进行硬降级容灾，确保系统高可用
        print("[反思纠错环路] 警告：已达到反思纠错次数硬上限。启用本地程序化安全兜底策略，以防系统瘫痪。")
        fallback_report = self._build_programmatic_fallback(records, feedback)
        return fallback_report, reflection_logs

    def _call_llm_api(self, records_json: str, feedback: str, attempt: int, simulate_hallucination: bool) -> str:
        """
        向大语言模型接口（或仿真模块）发送请求。
        """
        if config.USE_LLM_SIMULATION:
            return self._simulate_llm_response(records_json, feedback, attempt, simulate_hallucination)
            
        system_prompt = (
            "You are a sales operations AI Agent. Analyze the provided raw daily sales records and return a structured report in JSON.\n"
            "You must return a valid JSON object matching this structure:\n"
            "{\n"
            "  \"report_date\": \"YYYY-MM-DD\",\n"
            "  \"total_sales_amount\": float,\n"
            "  \"total_deals_count\": int,\n"
            "  \"salesperson_highlights\": [\n"
            "     {\"salesperson\": \"Name\", \"total_amount\": float, \"deal_count\": int}\n"
            "  ],\n"
            "  \"product_performance\": [\n"
            "     {\"product\": \"Name\", \"units_sold\": int, \"revenue\": float}\n"
            "  ],\n"
            "  \"anomalies\": [\"string\"],\n"
            "  \"trend_analysis\": \"detailed trend review string\"\n"
            "}\n\n"
            "CRITICAL RULES:\n"
            "1. Math: total_sales_amount MUST equal the sum of all transaction amounts.\n"
            "2. Grouping: salesperson total_amount and product revenue MUST sum up correctly based on raw data.\n"
            "3. Grounding: Do NOT invent names of salespeople or products that do not exist in the raw data (hallucination guardrail).\n"
            "4. Return ONLY valid JSON, no conversational text."
        )
        
        user_prompt = f"Raw Records:\n{records_json}\n\n"
        if feedback:
            user_prompt += f"--- CORRECTION REQUEST ---\n{feedback}\n\nPlease output the revised valid JSON daily report."
            
        response = self.llm_client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,  # 设定超低温度以确保数学统计和数据结构的确定性
            timeout=30
        )
        return response.choices[0].message.content

    def _simulate_llm_response(self, records_json: str, feedback: str, attempt: int, simulate_hallucination: bool) -> str:
        """
        （仿真模式下的 LLM 响应器）
        支持故意注入偏差以验证测试反射自愈链路。
        """
        today_str = time.strftime('%Y-%m-%d', time.localtime())
        
        if simulate_hallucination:
            print("[LLM 仿真响应器] 注入模拟数值幻觉/错算（第 1 次尝试）...")
            # 返回错误的销售总额：300k（实际应为 195k），并无中生有捏造销售员“马云”以及商品“幻觉产品组件”
            bad_report = {
                "report_date": today_str,
                "total_sales_amount": 300000.0,
                "total_deals_count": 6,
                "salesperson_highlights": [
                    {"salesperson": "王亮", "total_amount": 60000.0, "deal_count": 2},
                    {"salesperson": "李梅", "total_amount": 90000.0, "deal_count": 2},
                    {"salesperson": "张伟", "total_amount": 45000.0, "deal_count": 1},
                    {"salesperson": "马云", "total_amount": 105000.0, "deal_count": 1}  # 幻觉数据
                ],
                "product_performance": [
                    {"product": "AI企业级智能体助手", "units_sold": 2, "revenue": 90000.0},
                    {"product": "企业RAG私有知识库", "units_sold": 1, "revenue": 28000.0},
                    {"product": "数字人短视频生成系统", "units_sold": 1, "revenue": 15000.0},
                    {"product": "大模型定制微调服务", "units_sold": 1, "revenue": 62000.0},
                    {"product": "幻觉产品组件", "units_sold": 1, "revenue": 105000.0} # 幻觉数据
                ],
                "anomalies": ["无"],
                "trend_analysis": "今日销售强劲，新入职销售马云促成了一笔巨额订单。"
            }
            return json.dumps(bad_report)
            
        print("[LLM 仿真响应器] 模拟生成完美的销售看板 JSON...")
        # 真实总额: 45k + 28k + 15k + 45k + 62k = 195k
        # 王亮: 60k, 李梅: 90k, 张伟: 45k
        correct_report = {
            "report_date": today_str,
            "total_sales_amount": 195000.0,
            "total_deals_count": 5,
            "salesperson_highlights": [
                {"salesperson": "王亮", "total_amount": 60000.0, "deal_count": 2},
                {"salesperson": "李梅", "total_amount": 90000.0, "deal_count": 2},
                {"salesperson": "张伟", "total_amount": 45000.0, "deal_count": 1}
            ],
            "product_performance": [
                {"product": "AI企业级智能体助手", "units_sold": 2, "revenue": 90000.0},
                {"product": "企业RAG私有知识库", "units_sold": 1, "revenue": 28000.0},
                {"product": "数字人短视频生成系统", "units_sold": 1, "revenue": 15000.0},
                {"product": "大模型定制微调服务", "units_sold": 1, "revenue": 62000.0}
            ],
            "anomalies": ["无重大异常交易，大模型微调服务表现抢眼"],
            "trend_analysis": "今日销售势头强劲，核心产品AI智能体助手和定制微调服务贡献了超77%的营收。王亮和李梅业绩稳定双突破。"
        }
        return json.dumps(correct_report)

    def _extract_json_from_response(self, text: str) -> Dict[str, Any]:
        """
        优雅地剥离 Markdown 的 ```json 等标记，反序列化为 JSON 字典。
        """
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        return json.loads(text)

    def _validate_report_data(self, raw_records: List[SalesRecord], report: DailyReport) -> List[str]:
        """
        数据防线（Guardrails）：用 Python 原生代数算法进行事实比对，拦截 LLM 的财务错漏和捏造。
        """
        errors = []
        
        # 1. 强校验销售总额
        expected_total = sum(r.amount for r in raw_records)
        if abs(report.total_sales_amount - expected_total) > 0.01:
            errors.append(f"Total sales amount mismatch: LLM calculated {report.total_sales_amount}, but raw records sum is {expected_total}.")
            
        # 2. 强校验订单总数
        if report.total_deals_count != len(raw_records):
            errors.append(f"Total deals count mismatch: LLM calculated {report.total_deals_count}, but raw record count is {len(raw_records)}.")
            
        # 3. 强校验销售排行榜（求和、单数及有无捏造人员）
        raw_salesperson_totals = {}
        raw_salesperson_counts = {}
        for r in raw_records:
            raw_salesperson_totals[r.salesperson] = raw_salesperson_totals.get(r.salesperson, 0.0) + r.amount
            raw_salesperson_counts[r.salesperson] = raw_salesperson_counts.get(r.salesperson, 0) + 1
            
        reported_salespersons = set()
        for sh in report.salesperson_highlights:
            name = sh.salesperson
            reported_salespersons.add(name)
            if name not in raw_salesperson_totals:
                errors.append(f"Hallucination error: Salesperson '{name}' listed in report highlights does not exist in raw records.")
            else:
                expected_amt = raw_salesperson_totals[name]
                expected_cnt = raw_salesperson_counts[name]
                if abs(sh.total_amount - expected_amt) > 0.01:
                    errors.append(f"Calculation error: Salesperson '{name}' total amount in report ({sh.total_amount}) does not match raw records ({expected_amt}).")
                if sh.deal_count != expected_cnt:
                    errors.append(f"Calculation error: Salesperson '{name}' deal count in report ({sh.deal_count}) does not match raw records ({expected_cnt}).")
                    
        for name in raw_salesperson_totals:
            if name not in reported_salespersons:
                errors.append(f"Completeness error: Salesperson '{name}' exists in raw data but is missing from report highlights.")
                
        # 4. 强校验产品业绩分类明细（求和、售出量及有无捏造产品）
        raw_product_totals = {}
        raw_product_counts = {}
        for r in raw_records:
            raw_product_totals[r.product] = raw_product_totals.get(r.product, 0.0) + r.amount
            raw_product_counts[r.product] = raw_product_counts.get(r.product, 0) + 1
            
        reported_products = set()
        for pp in report.product_performance:
            p_name = pp.product
            reported_products.add(p_name)
            if p_name not in raw_product_totals:
                errors.append(f"Hallucination error: Product '{p_name}' listed in report does not exist in raw records.")
            else:
                expected_rev = raw_product_totals[p_name]
                expected_units = raw_product_counts[p_name]
                if abs(pp.revenue - expected_rev) > 0.01:
                    errors.append(f"Calculation error: Product '{p_name}' revenue in report ({pp.revenue}) does not match raw records ({expected_rev}).")
                if pp.units_sold != expected_units:
                    errors.append(f"Calculation error: Product '{p_name}' units sold in report ({pp.units_sold}) does not match raw records ({expected_units}).")
                    
        for p_name in raw_product_totals:
            if p_name not in reported_products:
                errors.append(f"Completeness error: Product '{p_name}' exists in raw data but is missing from product performance summaries.")
                
        return errors

    def _build_programmatic_fallback(self, raw_records: List[SalesRecord], feedback: str) -> DailyReport:
        """
        （硬兜底策略）
        当大模型多次纠错依然失败时，直接使用纯 Python 逻辑计算出绝对精准的统计看板数据。
        """
        today_str = time.strftime('%Y-%m-%d', time.localtime())
        
        # 本地绝对精确代数运算
        total_amt = sum(r.amount for r in raw_records)
        total_deals = len(raw_records)
        
        sp_totals = {}
        sp_counts = {}
        for r in raw_records:
            sp_totals[r.salesperson] = sp_totals.get(r.salesperson, 0.0) + r.amount
            sp_counts[r.salesperson] = sp_counts.get(r.salesperson, 0) + 1
            
        sp_highlights = [
            SalespersonHighlight(salesperson=k, total_amount=v, deal_count=sp_counts[k])
            for k, v in sp_totals.items()
        ]
        
        p_totals = {}
        p_counts = {}
        for r in raw_records:
            p_totals[r.product] = p_totals.get(r.product, 0.0) + r.amount
            p_counts[r.product] = p_counts.get(r.product, 0) + 1
            
        p_performance = [
            ProductPerformance(product=k, units_sold=v, revenue=p_totals[k])
            for k, v in p_counts.items()
        ]
        
        return DailyReport(
            report_date=today_str,
            total_sales_amount=total_amt,
            total_deals_count=total_deals,
            salesperson_highlights=sp_highlights,
            product_performance=p_performance,
            anomalies=[f"注意：系统启用了程序化容错计算（原因：大模型验证连续失败。最近一次错误：{feedback[:100]}...）"],
            trend_analysis="因大模型校验失败，今日报告采用系统固化的聚合算法计算得出，数据绝对准确，但未引入大模型语义深度分析。"
        )

    def _build_empty_state_card(self) -> Dict[str, Any]:
        """
        构造漂亮的飞书空数据预警看板卡片。
        """
        today_str = time.strftime('%Y-%m-%d', time.localtime())
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "grey",
                "title": {
                    "tag": "plain_text",
                    "content": f"📊 今日销售简报 ({today_str}) - 无交易数据"
                }
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "⚠️ **今日数据中心未获取到销售交易记录。**\n\n可能原因：\n1. 今日尚无销售订单结案。\n2. 多维表格同步延迟。\n\n请运营人员确认多维表格数据源录入情况。"
                    }
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "Feishu AI Reporting Agent • 运行正常 • 无活动记录"
                        }
                    ]
                }
            ]
        }

    def _build_report_card(self, report: DailyReport) -> Dict[str, Any]:
        """
        将结构化 DailyReport 报表对象渲染为高大上的飞书交互式消息卡片。
        运用了主题模板和样式规范来抓取眼球。
        """
        # 销售排行榜 markdown 排版
        sp_content = ""
        for sh in report.salesperson_highlights:
            sp_content += f"👤 **{sh.salesperson}** | 销售额: `￥{sh.total_amount:,.2f}` | 成交单数: `{sh.deal_count}`\n"
            
        # 产品业绩 markdown 排版
        p_content = ""
        for pp in report.product_performance:
            p_content += f"📦 **{pp.product}** | 销售量: `{pp.units_sold}` | 营业额: `￥{pp.revenue:,.2f}`\n"
            
        # 异常指标排版与情绪化警报
        anom_content = ""
        if report.anomalies:
            for an in report.anomalies:
                anom_content += f"🔴 {an}\n"
        else:
            anom_content = "🟢 今日无异常指标"
            
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": f"🚀 今日销售总结报告 ({report.report_date})"
                }
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"### 📈 今日核心业绩概览\n* **销售总额 (Total Revenue):** <font color='green'>**￥{report.total_sales_amount:,.2f}**</font>\n* **成交总单数 (Total Deals):** **{report.total_deals_count} 笔**"
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"### 👥 团队销售排行 (Highlights)\n{sp_content}"
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"### 📦 产品销售明细 (Product Performance)\n{p_content}"
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"### 🚨 异常预警 & 监控 (Anomalies)\n{anom_content}"
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"### 🧠 大模型趋势深度分析 (Trend Analysis)\n{report.trend_analysis}"
                    }
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')} • LLM Guardrail Certified"
                        }
                    ]
                }
            ]
        }
