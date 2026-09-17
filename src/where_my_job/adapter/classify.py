"""把一次 joblist 响应变成 typed 结果。只做分类，不做映射、不做网络；不保留平台 message 原文。"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from ..vendor.boss_zhipin_scraper.primitives import (classify_login_probe_response, LoginProbeStatus,
                                                     LOGIN_RESTRICTED_MESSAGE_KEYWORDS)

KINDS = ("success", "empty", "blocked", "unauthenticated", "unknown")
# 页面正文与非 JSON 响应的限制页特征：只用完整短语，避免"芯片验证工程师"之类误判。
RISK_TEXT_MARKERS = ("安全验证", "请完成验证", "完成验证后", "访问行为异常", "访问频繁", "操作太频繁",
                     "环境存在异常", "拖动滑块", "security-check")

@dataclass(frozen=True)
class Classified:
    kind: str
    code: int | None = None
    reason: str = ""                 # 固定内部原因码
    has_more: bool | None = None
    items: list = field(default_factory=list, repr=False)

def page_text_risk(text: str | None) -> bool:
    t = text or ""
    return any(m in t for m in RISK_TEXT_MARKERS)

def classify_joblist(data, http_status: int = 200) -> Classified:
    r = classify_login_probe_response(data, http_status=http_status)
    code = r.code if isinstance(r.code, int) else None
    if r.status is LoginProbeStatus.RESTRICTED:
        return Classified("blocked", code, "risk_response")
    if r.status is LoginProbeStatus.UNAUTHENTICATED:
        return Classified("unauthenticated", code, "unauthenticated_response")
    if r.status is LoginProbeStatus.RESPONSE_ERROR:
        return Classified("unknown", code, "response_error")
    zp = data.get("zpData") or {}
    raw_more = zp.get("hasMore")
    has_more = raw_more if isinstance(raw_more, bool) else None
    if r.status is LoginProbeStatus.EMPTY:
        if raw_more is False:
            return Classified("empty", code, "normal_end", has_more=False)
        return Classified("unknown", code, "empty_without_end_marker")
    items = [x for x in zp.get("jobList", []) if isinstance(x, dict)]
    return Classified("success", code, "ok", has_more=has_more, items=items)

def classify_body(body: str | None, http_status: int = 200) -> Classified:
    """捕获到的响应体：先按 JSON 分类；非 JSON 时只有出现限制页特征才判 blocked，否则 unknown。"""
    if body is None:
        return Classified("unknown", None, "body_unavailable")
    try:
        data = json.loads(body)
    except (json.JSONDecodeError, ValueError, TypeError):
        if page_text_risk(body) or any(k in body for k in LOGIN_RESTRICTED_MESSAGE_KEYWORDS if len(k) > 2):
            return Classified("blocked", None, "risk_page")
        return Classified("unknown", None, "non_json")
    return classify_joblist(data, http_status=http_status)

def body_note(c: Classified) -> str:
    """被丢弃响应的结构摘要：固定分类码、条目数、平台状态码与 hasMore 原值。
    不含岗位内容，也不含平台 message 原文——它要回答的只有一个问题：对方到底给没给数据。"""
    parts = [f"body:{c.kind}", f"items={len(c.items)}"]
    if c.code is not None:
        parts.append(f"code={c.code}")
    if c.has_more is not None:
        parts.append(f"has_more={'true' if c.has_more else 'false'}")
    return ",".join(parts)
