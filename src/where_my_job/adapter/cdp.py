"""真实 CDP 传输。只拦截 Document 请求；不注入请求、不改请求头、不注入页面脚本。"""
from __future__ import annotations
import base64, json, time
from typing import Callable
from urllib.parse import urlsplit
import websocket
from ..errors import EnvError
from ..public_messages import public_message
from .transport import Captured, DocumentDecision, JOBLIST_PATH
from ..browser_pages import BLANK_URLS, extra_pages, not_blank_error

_SCROLL_JS = "window.scrollTo(0, document.body ? document.body.scrollHeight : 0); 'ok'"
MAX_NAVIGATIONS = 16                                     # 观察记录的上限：诊断够用即可，不做无界累积

class CdpProtocolError(Exception):
    pass

class CdpConnection:
    def __init__(self, ws, on_event: Callable[[dict], None], monotonic: Callable[[], float]):
        self.ws, self.on_event, self.monotonic, self._mid = ws, on_event, monotonic, 0

    def post(self, method: str, params: dict | None = None, session_id: str | None = None) -> int:
        self._mid += 1
        msg = {"id": self._mid, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        self.ws.send(json.dumps(msg))
        return self._mid

    def _read_one(self, timeout: float) -> dict | None:
        self.ws.settimeout(max(0.05, min(timeout, 1.0)))
        try:
            raw = self.ws.recv()
        except websocket.WebSocketTimeoutException:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    def send(self, method: str, params: dict | None = None, session_id: str | None = None, timeout: float = 30.0) -> dict:
        mid = self.post(method, params, session_id)
        deadline = self.monotonic() + timeout
        while True:
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                raise TimeoutError(method)
            msg = self._read_one(remaining)
            if msg is None:
                continue
            if msg.get("id") == mid:
                return msg
            if "method" in msg:
                self.on_event(msg)

    def pump(self, duration: float) -> None:
        deadline = self.monotonic() + duration
        while self.monotonic() < deadline:
            msg = self._read_one(deadline - self.monotonic())
            if msg is not None and "method" in msg:
                self.on_event(msg)
            elif msg is None:
                return

class CdpTransport:
    @classmethod
    def open(cls, ws_url: str, *, target_id: str | None = None, connect=None,
             monotonic: Callable[[], float] = time.monotonic) -> "CdpTransport":
        ws = (connect or websocket.create_connection)(ws_url, timeout=30, suppress_origin=True,
                                                      http_no_proxy=["127.0.0.1", "::1", "localhost"])
        t = cls(ws, monotonic)
        t._setup(target_id)
        return t

    def __init__(self, ws, monotonic: Callable[[], float]):
        self.conn = CdpConnection(ws, self._on_event, monotonic)
        self.monotonic = monotonic
        self.session_id = ""
        self.frame_id = ""
        self.target_id = ""
        self._policy: Callable[[str, bool], DocumentDecision] = lambda url, main: DocumentDecision(False, "unknown")
        self._seq = 0
        self._requests: dict[str, dict] = {}
        self._status: dict[str, int] = {}
        self._finished: list[str] = []
        self._ready: list[Captured] = []
        self._blocked: list[tuple[str, str, bool]] = []      # (url, 判定, 是否主文档)
        self._doc = {"url": "about:blank", "frame_id": "", "loader_id": ""}
        self._guard = False                                  # Fetch 拦截是否开着
        self._navigations: list[str] = []                    # 主文档地址观察记录：拦截关掉之后唯一的可见性来源

    @staticmethod
    def _result(reply: dict, method: str) -> dict:
        if reply.get("error") is not None:
            raise CdpProtocolError(method)
        return reply.get("result") or {}

    def _setup(self, target_id: str | None = None) -> None:
        """新建模式：存在任何非空白页即拒绝（用户自己打开的页，或异常退出恢复的旧标签页）。
        附着模式：只允许记录的那一个登录页。与 launcher 的预检共用 browser_pages 的判定。"""
        infos = self._result(self.conn.send("Target.getTargets"), "Target.getTargets").get("targetInfos", [])
        if target_id is None:
            extra = extra_pages(infos)
            if extra:
                self.conn.ws.close()
                raise not_blank_error(extra)
            self.target_id = self._result(self.conn.send("Target.createTarget", {"url": "about:blank", "background": False}),
                                          "Target.createTarget")["targetId"]
        else:
            if not any(i.get("type") == "page" and i.get("targetId") == target_id for i in infos):
                self.conn.ws.close()
                raise EnvError("LOGIN_NOT_STARTED", public_message("LOGIN_NOT_STARTED"))
            extra = extra_pages(infos, allow_target_id=target_id)
            if extra:
                self.conn.ws.close()
                raise not_blank_error(extra)
            self.target_id = target_id
        self.session_id = self._result(self.conn.send("Target.attachToTarget", {"targetId": self.target_id, "flatten": True}),
                                       "Target.attachToTarget")["sessionId"]
        frame = self._result(self.conn.send("Page.getFrameTree", {}, self.session_id), "Page.getFrameTree")["frameTree"]["frame"]
        self.frame_id = frame["id"]
        self._doc = {"url": frame.get("url", "about:blank"), "frame_id": frame["id"], "loader_id": frame.get("loaderId", "")}
        for method, params in (("Page.enable", {}), ("Network.enable", {})):
            self._result(self.conn.send(method, params, self.session_id), method)

    # ---- 事件 ----
    def _on_event(self, msg: dict) -> None:
        method, params, sid = msg["method"], msg.get("params") or {}, msg.get("sessionId", "")
        if method == "Fetch.requestPaused":
            rid = params.get("requestId")
            url = (params.get("request") or {}).get("url", "")
            if params.get("resourceType") != "Document":
                self.conn.post("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"}, sid)
                return
            is_main = params.get("frameId") == self.frame_id
            decision = self._policy(url, is_main)
            if decision.allow:
                self.conn.post("Fetch.continueRequest", {"requestId": rid}, sid)
            else:
                self._blocked.append((url, decision.state, is_main))
                self.conn.post("Fetch.failRequest", {"requestId": rid, "errorReason": "BlockedByClient"}, sid)
        elif method == "Network.requestWillBeSent":
            self._seq += 1
            url = (params.get("request") or {}).get("url", "")
            try:
                path = urlsplit(url).path
            except ValueError:
                path = ""
            if path == JOBLIST_PATH:
                self._requests[params["requestId"]] = {"url": url, "session_id": sid, "frame_id": params.get("frameId", ""),
                                                       "loader_id": params.get("loaderId", ""), "sequence": self._seq}
        elif method == "Network.responseReceived":
            if params.get("requestId") in self._requests:
                self._status[params["requestId"]] = int((params.get("response") or {}).get("status", 0))
        elif method == "Network.loadingFinished":
            if params.get("requestId") in self._requests:
                self._finished.append(params["requestId"])
        elif method == "Network.loadingFailed":
            rid = params.get("requestId")
            if rid in self._requests:
                self._ready.append(self._captured(rid, None, "loading_failed"))
        elif method == "Page.frameNavigated":
            frame = params.get("frame") or {}
            if frame.get("id") == self.frame_id and not frame.get("parentId"):
                self._doc = {"url": frame.get("url", ""), "frame_id": frame["id"], "loader_id": frame.get("loaderId", "")}
                if not self._guard and len(self._navigations) < MAX_NAVIGATIONS:
                    self._navigations.append(frame.get("url", ""))   # 拦截开着时的跳转已由拦截记录覆盖，不重复记
        elif method == "Page.navigatedWithinDocument":
            if params.get("frameId") == self.frame_id:      # 同文档改址（pushState）：只换地址，不换 frame 与 loader
                self._doc = {**self._doc, "url": params.get("url", "")}

    def _captured(self, rid: str, body: str | None, error_text: str | None) -> Captured:
        meta = self._requests.pop(rid)
        return Captured(body=body, http_status=self._status.pop(rid, 0), request_id=rid, url=meta["url"],
                        session_id=meta["session_id"], frame_id=meta["frame_id"], loader_id=meta["loader_id"],
                        request_sequence=meta["sequence"], error_text=error_text)

    def _drain_finished(self) -> None:
        while self._finished:
            rid = self._finished.pop(0)
            sid = self._requests[rid]["session_id"]
            try:
                result = self._result(self.conn.send("Network.getResponseBody", {"requestId": rid}, sid, timeout=10), "body")
                body = result.get("body", "")
                if result.get("base64Encoded"):
                    body = base64.b64decode(body).decode("utf-8", errors="replace")
                self._ready.append(self._captured(rid, body, None))
            except (CdpProtocolError, TimeoutError, ValueError):
                self._ready.append(self._captured(rid, None, "body_unavailable"))

    # ---- 协议实现 ----
    def sequence(self) -> int:
        return self._seq

    def set_document_policy(self, policy) -> None:
        self._policy = policy

    def set_document_guard(self, on: bool) -> None:
        """文档拦截只在本工具自己发起的导航与登录流程期间开着。列表页提交之后关掉：
        平台的登录令牌握手带一次性令牌、对时序敏感，逐个暂停文档请求会把它打断——上游爬虫从不启用 Fetch，
        源码里连 passport/security.html 都没出现过。关掉之后靠 take_navigations 的观察、落点复核与捕获绑定把关。"""
        if on == self._guard:
            return
        if on:
            params = {"patterns": [{"resourceType": "Document", "requestStage": "Request"}]}
            self._result(self.conn.send("Fetch.enable", params, self.session_id), "Fetch.enable")
        else:
            self._result(self.conn.send("Fetch.disable", {}, self.session_id), "Fetch.disable")
        self._guard = on

    def take_navigations(self) -> list[str]:
        out, self._navigations = self._navigations, []
        return out

    def navigate(self, url: str) -> dict:
        self.set_document_guard(True)                   # 本工具自己的导航一律受拦截保护，与调用方是谁无关
        reply = self.conn.send("Page.navigate", {"url": url}, self.session_id, timeout=30)
        loader = (reply.get("result") or {}).get("loaderId")
        if loader and not (reply.get("result") or {}).get("errorText"):
            deadline = self.monotonic() + 10
            while self._doc.get("loader_id") != loader and self.monotonic() < deadline:
                self.conn.pump(0.5)
        return reply

    def scroll_bottom(self) -> None:
        self.conn.send("Runtime.evaluate", {"expression": _SCROLL_JS, "returnByValue": True}, self.session_id)

    def captures(self, timeout: float) -> list[Captured]:
        deadline = self.monotonic() + timeout
        while True:
            self._drain_finished()
            if self._ready:
                out, self._ready = self._ready, []
                return sorted(out, key=lambda c: c.request_sequence)
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                return []
            self.conn.pump(min(remaining, 0.5))

    def document(self) -> dict:
        return dict(self._doc)

    def evaluate(self, js: str) -> str | None:
        reply = self.conn.send("Runtime.evaluate", {"expression": js, "returnByValue": True}, self.session_id)
        result = reply.get("result") or {}
        if result.get("exceptionDetails"):
            return None
        value = (result.get("result") or {}).get("value")
        return value if isinstance(value, str) else None

    def screenshot(self) -> bytes | None:
        """当前视口的 PNG。只读取已渲染画面，不触发网络请求；失败或超时返回 None。"""
        try:
            reply = self.conn.send("Page.captureScreenshot", {"format": "png"}, self.session_id, timeout=10)
        except TimeoutError:
            return None
        data = (reply.get("result") or {}).get("data") if reply.get("error") is None else None
        if not isinstance(data, str):
            return None
        try:
            return base64.b64decode(data)
        except ValueError:
            return None

    def idle(self, seconds: float) -> None:
        """等待期间持续处理事件，Document 拦截与导航记录不停顿。"""
        deadline = self.monotonic() + seconds
        while True:
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                return
            self.conn.pump(min(remaining, 0.5))

    def take_blocked_documents(self) -> list[tuple[str, str, bool]]:
        out, self._blocked = self._blocked, []
        return out

    def close(self) -> None:
        try:
            if self.session_id:
                self.conn.post("Fetch.disable", {}, self.session_id)
            if self.target_id:
                self.conn.send("Target.closeTarget", {"targetId": self.target_id}, timeout=5)
        finally:
            self.conn.ws.close()

    def detach(self) -> None:
        """断开调试连接但保留标签页：扫码登录在两次命令之间需要登录页继续存在。"""
        try:
            if self.session_id:
                self.conn.post("Fetch.disable", {}, self.session_id)
                self.conn.post("Target.detachFromTarget", {"sessionId": self.session_id})
        finally:
            self.conn.ws.close()
