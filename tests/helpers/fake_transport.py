"""按脚本回放的传输替身，实现 adapter.transport.Transport 协议。脚本元素：
  ("page", snapshot)                   → 下一次 navigate 固定的页面快照；同一页面上 evaluate 多少次都返回它的深拷贝
  ("redirect", url)                    → 紧跟在下一次 navigate 之后的主文档重定向（逐个经过 Document 策略）
  ("subframe", url)                    → 下一次 navigate 时加载的子 frame 文档；被拒只记入拦截记录，导航继续
  ("new_document", url)                → 下一次 scroll_bottom 时页面尝试打开的新主文档
  ("joblist", payload, opts)           → 下一次 captures() 返回的本会话 joblist 响应；payload 为 dict、None 或 {"__not_json__":True,"body":str}
  ("foreign", payload)                 → 其他会话的 joblist 响应
  ("load_failed",)                     → 本会话 joblist 加载失败
  ("timeout",)                         → captures() 返回空列表
  ("doc_during_capture", url)          → 下一次 captures() 期间页面尝试打开的新主文档：经 Document 策略判定，被拒记入拦截记录；本次返回空列表
  ("hop", url)                         → 导航提交之后页面发起的新主文档：经 Document 策略判定；放行即换掉当前文档与 loader，随后继续处理本次 captures 的下一个脚本元素
  ("same_doc", url)                    → 下一次 scroll_bottom() 或 captures() 期间页面用 pushState 改址：不换文档、不经 Document 策略，只把当前地址换掉；被 captures() 消费时本次返回空列表
  ("doc_during_evaluate", url)         → 下一次 evaluate() 期间页面尝试打开的新主文档：先经策略判定，evaluate 仍返回当前页快照
opts 可含 http_status、url、query（覆盖查询参数）、session_id、loader_id、before_action（序号不增加）。
"""
from __future__ import annotations
import copy, json
from urllib.parse import urlsplit, parse_qsl, urlencode
from where_my_job.adapter.session import LIST_PATHS
from where_my_job.adapter.transport import Captured

class FakeTransport:
    session_id = "S-own"
    frame_id = "F-top"

    def __init__(self, script, *, close_error: str | None = None):
        self.script = list(script)
        self.navigations: list[str] = []
        self.documents_sent: list[str] = []
        self.scrolls = 0
        self.evaluations = 0
        self.closed = False
        self.close_error = close_error
        self._policy = None
        self.guard = False                              # 与真实传输一致：navigate 时开，调用方可关
        self._navigations: list[str] = []
        self._blocked: list[tuple[str, str, bool]] = []
        self._seq = 0
        self._loader_n = 0
        self._doc = {"url": "about:blank", "frame_id": self.frame_id, "loader_id": "L0"}
        self._page = None
        self._search_query: dict | None = None
        self._page_no = 0

    def sequence(self) -> int:
        return self._seq

    def set_document_policy(self, policy) -> None:
        self._policy = policy

    def set_document_guard(self, on: bool) -> None:
        self.guard = on

    def take_navigations(self) -> list[str]:
        out, self._navigations = self._navigations, []
        return out

    def _refused(self) -> dict:
        return {"id": 1, "result": {"frameId": self.frame_id, "loaderId": "", "errorText": "net::ERR_BLOCKED_BY_CLIENT"}}

    def navigate(self, url: str) -> dict:
        self.guard = True                           # 与真实传输一致：自己的导航一律受拦截保护
        self.navigations.append(url)
        chain = [url]
        while self.script and self.script[0][0] == "redirect":
            chain.append(self.script.pop(0)[1])
        subframes = []
        while self.script and self.script[0][0] == "subframe":
            subframes.append(self.script.pop(0)[1])
        for doc_url in chain:
            decision = self._policy(doc_url, True)
            if not decision.allow:
                self._blocked.append((doc_url, decision.state, True))
                return self._refused()
            self.documents_sent.append(doc_url)
        for sub in subframes:
            decision = self._policy(sub, False)
            if decision.allow:
                self.documents_sent.append(sub)
            else:
                self._blocked.append((sub, decision.state, False))   # 真实浏览器里被拒的子文档不会中断主文档
        self._loader_n += 1
        final = chain[-1]
        self._doc = {"url": final, "frame_id": self.frame_id, "loader_id": f"L{self._loader_n}"}
        parts = urlsplit(final)
        if parts.path in LIST_PATHS:                    # 列表页两种拼法都要认，否则跳到复数路径后查询参数会丢
            self._search_query = dict(parse_qsl(parts.query))
            self._page_no = int(self._search_query.get("page", "1"))
        self._page = None
        if self.script and self.script[0][0] == "page":
            self._page = copy.deepcopy(self.script.pop(0)[1])
        return {"id": 1, "result": {"frameId": self.frame_id, "loaderId": self._doc["loader_id"]}}

    def activate(self) -> bool:
        self.activated = self.activated + 1 if hasattr(self, "activated") else 1
        return True

    def scroll_bottom(self) -> None:
        self.scrolls += 1
        self._page_no += 1
        while self.script and self.script[0][0] == "same_doc":   # 翻页前页面自己改了地址：不换文档，只换地址
            self._doc = {**self._doc, "url": self.script.pop(0)[1]}
        while self.script and self.script[0][0] == "new_document":
            self._offer_document(self.script.pop(0)[1])

    def _offer_document(self, url: str, main: bool = True) -> None:
        if not self.guard:                          # 拦截已关：文档照常加载，只被观察到
            self._land(url, main)
            return
        decision = self._policy(url, main)
        if decision.allow:
            self._land(url, main)
        else:
            self._blocked.append((url, decision.state, main))

    def _land(self, url: str, main: bool) -> None:
        self.documents_sent.append(url)
        if main:                                    # 真实浏览器里生效的主文档会换掉当前文档，loader 随之改变
            self._loader_n += 1
            self._doc = {"url": url, "frame_id": self.frame_id, "loader_id": f"L{self._loader_n}"}
            if not self.guard:                      # 只记没被拦截覆盖的跳转
                self._navigations.append(url)

    def captures(self, timeout: float) -> list[Captured]:
        while self.script and self.script[0][0] == "hop":   # 导航提交后的主文档：判定后继续本次 captures，不像 doc_during_capture 那样直接返回空
            self._offer_document(self.script.pop(0)[1])
        if not self.script:
            return []
        kind = self.script[0][0]
        if kind == "doc_during_capture":
            self._offer_document(self.script.pop(0)[1])
            return []
        if kind == "same_doc":                      # 同文档改址：不经策略，只换地址，loader 不变
            self._doc = {**self._doc, "url": self.script.pop(0)[1]}
            return []
        if kind == "timeout":
            self.script.pop(0)
            return []
        if kind not in ("joblist", "foreign", "load_failed"):
            return []
        step = self.script.pop(0)
        payload = step[1] if len(step) > 1 else None
        opts = step[2] if len(step) > 2 else {}
        if isinstance(payload, dict) and payload.get("__not_json__"):
            body = payload["body"]
        else:
            body = None if payload is None else json.dumps(payload, ensure_ascii=False)
        query = dict(self._search_query or {})
        query["page"] = str(self._page_no)
        query.update(opts.get("query", {}))
        url = opts.get("url") or "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?" + urlencode(query)
        if not opts.get("before_action"):
            self._seq += 1
        seq = self._seq
        return [Captured(
            body=None if kind == "load_failed" else body,
            http_status=opts.get("http_status", 200), request_id=f"req-{seq}-{len(self.navigations)}-{self.scrolls}",
            url=url, session_id="S-other" if kind == "foreign" else opts.get("session_id", self.session_id),
            frame_id=self.frame_id, loader_id=opts.get("loader_id", self._doc["loader_id"]), request_sequence=seq,
            error_text="loading_failed" if kind == "load_failed" else None)]

    def document(self) -> dict:
        return dict(self._doc)

    def evaluate(self, js: str):
        self.evaluations += 1
        while self.script and self.script[0][0] == "doc_during_evaluate":
            self._offer_document(self.script.pop(0)[1])
        if self._page is None:
            return None
        snap = copy.deepcopy(self._page)
        snap.setdefault("url", self._doc["url"])
        return json.dumps(snap, ensure_ascii=False)

    def take_blocked_documents(self) -> list[tuple[str, str, bool]]:
        out, self._blocked = self._blocked, []
        return out

    def close(self) -> None:
        self.closed = True
        if self.close_error:
            raise RuntimeError(self.close_error)
