import os
from dotenv import load_dotenv

# 从项目根目录下的 .env 文件加载环境变量（若存在）
load_dotenv()

# 飞书 API 凭证配置
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_BITABLE_APP_TOKEN = os.getenv("FEISHU_BITABLE_APP_TOKEN", "")
FEISHU_BITABLE_TABLE_ID = os.getenv("FEISHU_BITABLE_TABLE_ID", "")
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")

# 大语言模型 (LLM) API 配置
# 默认 Base URL 指向 OpenAI，但支持任何兼容 OpenAI 接口规范的国产大模型及代理（如 DeepSeek、通义千问、文心一言代理等）
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

# 稳定性与重试设置
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BACKOFF_FACTOR = float(os.getenv("RETRY_BACKOFF_FACTOR", "2.0"))
MAX_REFLECTION_ATTEMPTS = int(os.getenv("MAX_REFLECTION_ATTEMPTS", "3"))

# 仿真/模拟模式判定 (若凭证或密钥留空，则强制开启本地模拟，确保代码可独立运行测试)
USE_FEISHU_SIMULATION = FEISHU_APP_ID == "" or FEISHU_APP_SECRET == "" or FEISHU_BITABLE_APP_TOKEN == ""
USE_LLM_SIMULATION = LLM_API_KEY == ""

print(f"[配置加载完成] 飞书模拟模式: {USE_FEISHU_SIMULATION}, LLM 模拟模式: {USE_LLM_SIMULATION}")
