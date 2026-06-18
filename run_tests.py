import time
import requests
import json
from typing import List
from unittest.mock import patch, MagicMock
from src.feishu_client import FeishuClient
from src.agent_workflow import AgentWorkflow
from src.models import SalesRecord
import src.config as config

def run_scenario_1_happy_path():
    print("\n" + "="*50)
    print("场景 1: Happy Path 正常流测试 (本地仿真模式)")
    print("="*50)
    
    workflow = AgentWorkflow()
    result = workflow.run(simulate_hallucination=False)
    
    assert result["status"] == "success"
    assert result["report"] is not None
    assert result["report"]["total_sales_amount"] == 195000.0
    assert len(result["report"]["salesperson_highlights"]) == 3
    print("[成功] 场景 1 测试通过：销售简报正常拉取、模型总结并通过 guardrails 验证！")

def run_scenario_2_empty_data():
    print("\n" + "="*50)
    print("场景 2: 边界情况 - 飞书多维表格空数据拦截")
    print("="*50)
    
    # 模拟飞书拉取结果为空列表
    feishu_mock = FeishuClient()
    feishu_mock.fetch_bitable_records = MagicMock(return_value=[])
    feishu_mock.push_to_group_webhook = MagicMock(return_value=True)
    
    workflow = AgentWorkflow(feishu_client=feishu_mock)
    result = workflow.run()
    
    assert result["status"] == "success"
    assert result["report"] is None
    feishu_mock.push_to_group_webhook.assert_called_once()
    print("[成功] 场景 2 测试通过：空交易数据被优雅拦截并向群内发布灰色无交易预警！")

def run_scenario_3_hallucination_reflection():
    print("\n" + "="*50)
    print("场景 3: 边界情况 - 捕获大模型计算幻觉与反思自我纠错循环")
    print("="*50)
    
    workflow = AgentWorkflow()
    # 触发 simulate_hallucination=True 强制让模拟大模型在 Attempt 1 输出错误指标和虚假人名
    result = workflow.run(simulate_hallucination=True)
    
    logs = result["reflection_logs"]
    print(f"\n--- [反思日志追踪] (总迭代轮数: {len(logs)}) ---")
    for log in logs:
        print(f"轮次 {log['attempt']}: 状态 = {log['status']}")
        if log['errors']:
            print(f"  捕获到的数据指标违规 details: {log['errors']}")
            
    assert len(logs) == 2, f"预期迭代轮数应正好为 2 轮，实际为 {len(logs)}"
    assert logs[0]["status"] == "FAILED", "第 1 次生成应该未通过代数强验证"
    assert logs[1]["status"] == "PASSED", "第 2 次修正生成应该通过全部验证"
    assert result["report"]["total_sales_amount"] == 195000.0, "最终修正后的销售总额应与原始数据完全对齐"
    
    # 断言第一轮的报错中正确捕获了“虚假姓名”和“金额算错”
    first_attempt_errors = logs[0]["errors"]
    assert any("Hallucination error" in err for err in first_attempt_errors), "应捕获虚假人名或产品"
    assert any("Total sales amount mismatch" in err for err in first_attempt_errors), "应捕获销售总额错算"
    
    print("\n[成功] 场景 3 测试通过：校验防线成功拦截财务错算，大模型结合反馈实现了在 Attempt 2 自愈纠错！")

def run_scenario_4_network_retry():
    print("\n" + "="*50)
    print("场景 4: 边界情况 - 接口限流与 503 临时抖动指数退避重试")
    print("="*50)
    
    feishu_client = FeishuClient()
    feishu_client._get_tenant_access_token = MagicMock(return_value="mock_token")
    
    # 模拟前 2 次请求均因 503 网络错误挂掉，第 3 次成功返回
    mock_responses = [
        requests.exceptions.HTTPError("503 Service Unavailable"),
        requests.exceptions.HTTPError("503 Service Unavailable"),
        "success"
    ]
    
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        resp = mock_responses[call_count]
        call_count += 1
        if isinstance(resp, Exception):
            print(f"  [模拟网络层] 模拟外部接口抛出 503 Service 崩溃 (重试计数: {call_count})...")
            raise resp
        print("  [模拟网络层] 模拟外部接口在第 3 次请求时恢复正常！")
        
        # 返回成功响应
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "code": 0,
            "msg": "success",
            "data": {
                "items": [
                    {
                        "record_id": "rec999",
                        "fields": {
                            "Salesperson": "Zhang San",
                            "Product": "Test Product",
                            "Amount": 100.0,
                            "Customer": "Test Customer",
                            "Date": "2026-06-18"
                        }
                    }
                ],
                "has_more": False
            }
        }
        return mock_resp
        
    with patch('src.feishu_client.requests.get', side_effect=side_effect):
        with patch('src.config.USE_FEISHU_SIMULATION', False):
            records = feishu_client.fetch_bitable_records(app_token="mock_app", table_id="mock_table")
        
    assert len(records) == 1
    assert records[0].salesperson == "Zhang San"
    assert call_count == 3
    print("[成功] 场景 4 测试通过：Tenacity 成功拦截 503 接口崩溃，并进行指数退避睡眠，第 3 次成功拉取！")

def run_scenario_5_reflection_hard_fallback():
    print("\n" + "="*50)
    print("场景 5: 极端情况 - 大模型连续反思失败自动启动 Python 代数硬兜底")
    print("="*50)
    
    workflow = AgentWorkflow()
    
    # 模拟大模型因网络干扰或严重幻觉，反复输出同一个错误的销售报表（总额 999999.9）
    # 设定反思上限次数为 2 以加速测试
    with patch('src.config.MAX_REFLECTION_ATTEMPTS', 2):
        with patch.object(workflow, '_call_llm_api', return_value=json.dumps({
            "report_date": "2026-06-18",
            "total_sales_amount": 999999.9, # 严重错误的销售总额
            "total_deals_count": 99,
            "salesperson_highlights": [],
            "product_performance": [],
            "anomalies": [],
            "trend_analysis": "Broken"
        })):
            result = workflow.run()
            
    assert result["status"] == "success"
    # 兜底报表的销售总额应该为本地 Python 程序硬计算得出的真实总额（195,000.00）
    assert result["report"]["total_sales_amount"] == 195000.0
    assert "程序化容错计算" in result["report"]["anomalies"][0]
    print("[成功] 场景 5 测试通过：在大模型多次验证失败后，工作流安全降级并依靠 Python 完成精准聚合，保障管道不崩溃！")

if __name__ == "__main__":
    print("="*60)
    print("飞书每日销售看板 AI Agent - 稳定性与高可用自动化测试套件")
    print("="*60)
    
    start_time = time.time()
    
    run_scenario_1_happy_path()
    run_scenario_2_empty_data()
    run_scenario_3_hallucination_reflection()
    run_scenario_4_network_retry()
    run_scenario_5_reflection_hard_fallback()
    
    duration = time.time() - start_time
    print("\n" + "="*60)
    print(f"恭喜！所有 5 大高可用稳定性边界测试场景均已验证通过！总用时: {duration:.2f}s")
    print("="*60)
