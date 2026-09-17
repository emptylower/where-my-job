"""捕获记录、动作期望、匹配谓词与传输协议。纯数据与纯函数，不做 IO。"""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Callable, Protocol
from urllib.parse import urlsplit, parse_qs

JOBLIST_PATH = "/wapi/zpgeek/search/joblist.json"

@dataclass(frozen=True)
class Captured:
    body: str | None
    http_status: int
    request_id: str
    url: str
    session_id: str
    frame_id: str
    loader_id: str
    request_sequence: int
    error_text: str | None = None

@dataclass(frozen=True)
class ActionExpectation:
    action_id: str
    session_id: str
    frame_id: str
    loader_id: str | None
    keyword: str
    city_code: str
    page: int
    canonical_filters: dict
    started_sequence: int

@dataclass(frozen=True)
class DocumentDecision:
    allow: bool
    state: str                  # ok | unauthenticated | blocked | unknown

def match_failure(expected, captured) -> str | None:
    """这条响应为什么不属于本次动作：返回固定原因码，属于本次动作则返回 None。
    只看结构字段（会话、文档、顺序、端点与查询参数），不看响应内容，因此可以原样交回信封。"""
    if not expected.loader_id:
        return "unbound_action"
    if captured.session_id != expected.session_id:
        return "other_session"
    if captured.frame_id != expected.frame_id or captured.loader_id != expected.loader_id:
        return "other_document"
    if captured.request_sequence <= expected.started_sequence:
        return "before_action"
    try:
        url = urlsplit(captured.url)
        if (url.scheme != "https" or url.hostname != "www.zhipin.com" or url.port not in (None, 443)
                or url.username or url.password or url.fragment or url.path != JOBLIST_PATH):
            return "other_endpoint"
        query = parse_qs(url.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return "other_endpoint"
    required = {"query": expected.keyword, "city": expected.city_code, "page": str(expected.page)}
    required.update(expected.canonical_filters)
    present = [key for key in required if key in query]     # 平台已把搜索条件移出接口地址，地址上只剩防缓存参数
    if present and not all(query.get(key) == [str(required[key])] for key in present):
        return "other_parameters"                           # 带了就必须一致：挡住同一文档里翻错页的响应
    return None

def request_matches(expected, captured) -> bool:
    return match_failure(expected, captured) is None

def parameter_mismatch(expected, captured) -> tuple[str, ...]:
    """必需参数逐项判定，只供诊断：回参数名与不符类型（missing 缺失、duplicated 同名多值、differs 值不同），
    不回参数值——参数名与期望值都出自本工具自己的输入，不含页面内容。全部相符或查询串解析不了时返回空元组。"""
    try:
        values = parse_qs(urlsplit(captured.url).query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return ()
    required = {"query": expected.keyword, "city": expected.city_code, "page": str(expected.page)}
    required.update(expected.canonical_filters)
    out: list[str] = []
    for key, value in required.items():
        got = values.get(key)
        if got is None:
            out.append(f"{key}=missing")
        elif len(got) > 1:
            out.append(f"{key}=duplicated")
        elif got[0] != str(value):
            out.append(f"{key}=differs")
    return tuple(out)

def parameters_verified(expected, captured) -> bool:
    """这条响应的地址里有没有可核对的必需参数。一个都没有时绑定只能靠文档与顺序，调用方据此记一条诊断。"""
    try:
        query = parse_qs(urlsplit(captured.url).query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    required = {"query", "city", "page", *expected.canonical_filters}
    return any(key in query for key in required)

def bind_navigation_result(expected, reply):
    if expected.loader_id is not None:
        raise ValueError("navigation expectation must start unbound")
    if not isinstance(reply, dict) or reply.get("error") is not None:
        raise ValueError("navigation command failed")
    result = reply.get("result")
    if not isinstance(result, dict):
        raise ValueError("navigation result missing")
    loader = result.get("loaderId")
    if (result.get("errorText") or result.get("isDownload")
            or result.get("frameId") != expected.frame_id
            or not isinstance(loader, str) or not loader):
        raise ValueError("navigation document not established")
    return replace(expected, loader_id=loader)

class Transport(Protocol):
    session_id: str
    frame_id: str
    target_id: str
    def sequence(self) -> int: ...
    def set_document_policy(self, policy: Callable[[str, bool], DocumentDecision]) -> None: ...
    def set_document_guard(self, on: bool) -> None: ...                    # 文档拦截开关：只在导航与登录流程期间开
    def take_navigations(self) -> list[str]: ...                           # 观察到的主文档地址，取走即清空
    def navigate(self, url: str) -> dict: ...
    def activate(self) -> bool: ...                                    # 标签页激活 + 窗口置前；失败不致命
    def scroll_bottom(self) -> None: ...
    def captures(self, timeout: float) -> list[Captured]: ...
    def document(self) -> dict: ...
    def evaluate(self, js: str) -> str | None: ...
    def screenshot(self) -> bytes | None: ...
    def idle(self, seconds: float) -> None: ...
    def take_blocked_documents(self) -> list[tuple[str, str, bool]]: ...   # (url, 判定, 是否主文档)
    def detach(self) -> None: ...
    def close(self) -> None: ...
