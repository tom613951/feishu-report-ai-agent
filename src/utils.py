import sys
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import requests

# 设置全局标准输出日志格式
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("FeishuAgent")

def is_retryable_http_error(exception: Exception) -> bool:
    """
    判断网络异常是否属于可重试的范围
    （如 429 请求限流、5xx 服务端临时崩溃、以及连接超时等）。
    """
    if isinstance(exception, requests.exceptions.RequestException):
        if exception.response is not None:
            status = exception.response.status_code
            # 429 Too Many Requests，500/502/503/504 均为服务端临时错误，需启动退避重试
            if status in [429, 500, 502, 503, 504]:
                logger.warning(f"[网络监控] 捕获到可重试的 HTTP 异常: 状态码 {status}")
                return True
        else:
            # 物理断网、请求超时、连接拒绝也支持重试
            logger.warning("[网络监控] 捕获到网络连接超时/网络中断。")
            return True
    return False

# 通用的 Tenacity 指数退避重试装饰器，用于封装所有网络调用（飞书 API 和大模型 API）
network_retry_decorator = retry(
    stop=stop_after_attempt(3), # 最高重试 3 次
    wait=wait_exponential(multiplier=2, min=1, max=10), # 指数级别等待时长（以2为底乘数，1s到10s之间）
    retry=retry_if_exception_type(requests.exceptions.RequestException), # 对所有 Requests 请求异常重试
    reraise=True, # 失败耗尽后重新抛出异常，触发业务逻辑兜底或中断
    before_sleep=lambda retry_state: logger.info(
        f"[重试监控] 请求失败。正在进行第 {retry_state.attempt_number} 次重试，正在等待网络回退系数计时器..."
    )
)
