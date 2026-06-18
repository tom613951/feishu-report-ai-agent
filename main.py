import sys
from src.agent_workflow import AgentWorkflow
from src.feishu_client import FeishuClient
import src.config as config

def main():
    print("=========================================")
    print(" 飞书每日销售看板 AI Agent 启动程序")
    print("=========================================")
    
    # 检测运行模式
    if config.USE_FEISHU_SIMULATION:
        print("[警告] 检测到飞书凭证为空，当前正运行于 飞书模拟数据模式。")
    else:
        print("[信息] 成功读取飞书自建应用凭证，将拉取真实飞书多维表格数据！")
        
    if config.USE_LLM_SIMULATION:
        print("[警告] 检测到大模型 API 密钥为空，当前正运行于 大模型模拟生成模式。")
    else:
        print(f"[信息] 成功检测到大模型 API 密钥。")
        print(f"      API 地址: {config.LLM_BASE_URL}")
        print(f"      使用模型: {config.LLM_MODEL}")
        
    print("=========================================")
    print("正在执行工作流管道...")
    
    try:
        workflow = AgentWorkflow()
        result = workflow.run()
        
        print("\n=========================================")
        print("🎉 工作流执行成功！")
        if result.get("report"):
            print(f"📊 看板日期: {result['report']['report_date']}")
            print(f"💰 今日销售总额: ￥{result['report']['total_sales_amount']:,.2f}")
            print(f"🤝 成交笔数: {result['report']['total_deals_count']}")
        print("=========================================")
    except Exception as e:
        print(f"\n[错误] 工作流执行中断: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
