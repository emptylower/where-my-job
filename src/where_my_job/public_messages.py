"""公开 JSON、run_tasks、runs.summary 与 stdout 只允许出现这些固定文案。
禁止把 URL、页面正文、平台 message、异常字符串拼进公开输出。"""
from __future__ import annotations

PUBLIC_FAILURE_MESSAGES: dict[str, str] = {
    "RISK_DETECTED": "检测到平台访问限制，已停止并进入冷却",
    "UNAUTHENTICATED": "专用浏览器会话未登录或登录已失效",
    "CAPTURE_UNKNOWN": "未取得可验证的页面响应，已停止",
    "CAPTURE_FAILED": "未取得可验证的页面响应且没有已保存结果，已停止",
    "PARTIAL_RESULT": "计划未完成，已保存部分有效结果",
    "COOLDOWN_ACTIVE": "专用浏览器仍在冷却中",
    "BUDGET_EXHAUSTED": "本次计划超过可用动作额度",
    "RESOURCE_BUSY": "专用浏览器正在被另一操作使用",
    "CLOCK_ANOMALY": "系统时间早于上次记录的网络动作时间，已停止在线操作",
    "CDP_UNAVAILABLE": "专用浏览器调试入口不可用",
    "CDP_NOT_LOOPBACK": "专用浏览器调试入口不是本机回环监听，已拒绝连接",
    "PROFILE_NOT_OWNED": "浏览器进程或会话不属于本工具的专用配置，已拒绝操作",
    "BROWSER_NOT_BLANK": "专用浏览器里还开着其它标签页，已拒绝操作",
    "DISK_ERROR": "本地数据写入失败，已保留此前提交的结果",
    "LOGIN_NOT_STARTED": "没有进行中的扫码登录，或登录页已被关闭",
    "LOGIN_TIMEOUT": "扫码登录已超时或二维码已过期，请重新开始登录",
    "INTERNAL": "内部错误，已停止",
}

def public_message(code: str) -> str:
    return PUBLIC_FAILURE_MESSAGES.get(code, PUBLIC_FAILURE_MESSAGES["INTERNAL"])
