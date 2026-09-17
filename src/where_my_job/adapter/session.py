"""导航白名单 + 发出前 Document 策略 + 绑定本次动作的捕获 + 读取前后复核。只从校验后的 ID 构造 URL。"""
from __future__ import annotations
import itertools, json, re, time
from dataclasses import dataclass, field, replace
from urllib.parse import urlsplit
from ..vendor.boss_zhipin_scraper.primitives import (build_search_url, PROBE_CAPTURE_TIMEOUT, EXTRACT_DETAIL_JS,
                                                     DETAIL_LOGIN_MARKER)
from .classify import Classified, body_note, classify_body, page_text_risk
from .transport import (ActionExpectation, DocumentDecision, Transport, bind_navigation_result, match_failure,
                        parameter_mismatch, parameters_verified)
from ..redact import redact_url

SOURCE_ID = re.compile(r"[A-Za-z0-9~_-]{1,128}")
ALLOWED_URL = re.compile(r"https://www\.zhipin\.com/(?:web/geek/job\?[A-Za-z0-9%._~=&+-]*"
                         r"|job_detail/[A-Za-z0-9~_-]{1,128}\.html|gongsi/[A-Za-z0-9~_-]{1,128}\.html)")
LOGIN_PATH = re.compile(r"^/web/user(?:/|$)")
SECURITY_PATH = re.compile(r"^/web/common/security-check|^/web/passport/zp/verify|captcha|verify-slider")
HANDSHAKE_PATH = re.compile(r"^/web/passport/zp/")      # 平台自己的登录握手/验证家族页：停在这里即未走完
LIST_PATHS = ("/web/geek/job", "/web/geek/jobs")        # 同一个搜索列表页的两种拼法：平台改了路径名，两种都要认
MAX_PAGE_TEXT = 12000
MAX_DOCUMENT_NOTES = 8

# 应用自有读取脚本：只读 DOM，不发请求。与 vendor EXTRACT_DETAIL_JS 分别执行，互不修改。
EXTRACT_PAGE_JS = """
(function(){
  var text = document.body ? document.body.innerText : '';
  var ld = [];
  document.querySelectorAll('script[type="application/ld+json"]').forEach(function(s){ ld.push((s.textContent || '').substring(0, 20000)); });
  return JSON.stringify({page_text: text.substring(0, 12000), text_truncated: text.length > 12000, ldjson: ld.slice(0, 8), url: location.href});
})()
"""

class NavigationRefused(ValueError):
    pass

@dataclass(frozen=True)
class PageResult:
    kind: str                           # success | empty | blocked | unauthenticated | unknown
    reason: str                         # 固定内部原因码
    classified: Classified | None = None
    request_id: str | None = None
    platform_code: int | None = None
    ignored_responses: int = 0
    ignored_reasons: dict = field(default_factory=dict)  # 丢弃原因码计数：分清"接口没发出"与"哪一项不符"
    refused_subframes: int = 0          # 被拒绝的站外子文档数量：设计内行为，不是失败原因
    notes: tuple[str, ...] = ()         # 脱敏文档诊断：main/sub + 判定 + 主机路径与参数名

@dataclass(frozen=True)
class DetailRead:
    kind: str                           # ok | blocked | unauthenticated | unknown
    reason: str
    extracted: dict | None = None
    refused_subframes: int = 0
    notes: tuple[str, ...] = ()

def _site_state(url: str) -> str | None:
    """同站 https 且无端口/凭据/片段时返回 'login'/'security'/'site'，否则 None。"""
    try:
        p = urlsplit(url)
        if (p.scheme != "https" or p.hostname != "www.zhipin.com" or p.port not in (None, 443)
                or p.username or p.password or p.fragment):
            return None
    except ValueError:
        return None
    if LOGIN_PATH.match(p.path):
        return "login"
    if SECURITY_PATH.search(p.path):
        return "security"
    return "site"

def same_document(url: str, expected: str | None) -> bool:
    """同一主文档：地址逐字符相同，或同为站内页面且路径相同——平台会给主文档追加跟踪参数。
    列表页的两种拼法（`LIST_PATHS`）算同一页：平台把这个路径改了名，我们仍然请求原地址、跟随它自己的跳转。
    只放宽这一对路径；站点、协议、端口、登录页与验证页的判定一概不动。"""
    if expected is None or not isinstance(url, str):
        return False
    if url == expected:
        return True
    if _site_state(url) != "site" or _site_state(expected) != "site":
        return False
    try:
        path, want = urlsplit(url).path, urlsplit(expected).path
    except ValueError:
        return False
    return path == want or (path in LIST_PATHS and want in LIST_PATHS)

def classify_document_url(url: str, expected_url: str | None) -> str:
    """导航进行中（expected_url 非空）放行同站主文档：平台会在一次导航里插入自己的跳转，
    普通浏览器自行跟随。登录页、验证页与站外文档一律拒绝；导航结束后不再接受新的主文档。
    放行不等于承认结果：最终落点由 _doc_ok 复核，不符即终止本次动作。"""
    site = _site_state(url)
    if site is None:
        return "unknown"
    if site == "login":
        return "unauthenticated"
    if site == "security":
        return "blocked"
    return "ok" if expected_url is not None else "unknown"

def _json_obj(raw) -> dict | None:
    try:
        obj = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None

_REASON = {"blocked": "risk_redirect", "unauthenticated": "login_redirect"}

class BrowserSession:
    def __init__(self, transport: Transport, *, capture_timeout: float = PROBE_CAPTURE_TIMEOUT, monotonic=time.monotonic):
        self.t = transport
        self.capture_timeout = capture_timeout
        self.monotonic = monotonic
        self._expected_url: str | None = None
        self._last: ActionExpectation | None = None
        self._last_url: str | None = None
        self._ids = itertools.count(1)
        self._refused_subframes = 0
        self._notes: list[str] = []
        self._action_url: str | None = None             # 本次动作绑定的地址：观察记录据此判断哪些跳转值得记
        transport.set_document_policy(self._decide)

    def _decide(self, url: str, is_main_frame: bool) -> DocumentDecision:
        if is_main_frame:
            state = classify_document_url(url, self._expected_url)
            return DocumentDecision(state == "ok", state)
        site = _site_state(url)
        if site == "site":
            return DocumentDecision(True, "ok")
        return DocumentDecision(False, {"login": "unauthenticated", "security": "blocked"}.get(site, "unknown"))

    def navigate_checked(self, url: str) -> None:
        if not isinstance(url, str) or not ALLOWED_URL.fullmatch(url):
            raise NavigationRefused("navigation target refused")

    def _settled_onto(self, exp: ActionExpectation, url: str | None) -> bool:
        """页面自己换过文档之后：顶层 frame 没变、文档换了（loader 不同）、落点仍是期望页。三条同时成立才重新绑定。"""
        doc = self.t.document()
        return (doc.get("frame_id") == exp.frame_id and doc.get("loader_id") != exp.loader_id
                and same_document(str(doc.get("url") or ""), url))

    # ---- 本次动作的文档诊断 ----
    def _begin(self) -> None:
        self._refused_subframes = 0
        self._notes = []
        self._action_url = None

    def _fill(self, result):
        return replace(result, refused_subframes=self._refused_subframes, notes=tuple(self._notes))

    def _blocked_result(self) -> PageResult | None:
        """先把观察到的主文档地址记进诊断，再取出被 Document 策略拒绝的文档并判定。
        拦截只覆盖本工具自己的导航；提交之后页面自己的跳转靠观察记录（`saw:`）可见，靠落点复核与捕获绑定把关。
        主文档被拒一律终止：风控 > 未登录 > 非预期地址。站外子文档被拒是设计内行为，只记数与记录，不终止。"""
        for seen in self.t.take_navigations():
            if not same_document(seen, self._action_url) and len(self._notes) < MAX_DOCUMENT_NOTES:
                self._notes.append(f"saw:{redact_url(seen)}")
        fatal: set[str] = set()
        for url, state, is_main in self.t.take_blocked_documents():
            if len(self._notes) < MAX_DOCUMENT_NOTES:
                self._notes.append(f"{'main' if is_main else 'sub'}:{state}:{redact_url(url)}")
            if is_main or state in ("blocked", "unauthenticated"):
                fatal.add(state)
            else:
                self._refused_subframes += 1
        for state in ("blocked", "unauthenticated"):
            if state in fatal:
                return PageResult(state, _REASON[state])
        if fatal:
            return PageResult("unknown", "unexpected_document")
        return None

    def _navigate(self, url: str):
        self.navigate_checked(url)
        pending = self._blocked_result()                # 上一步之后到达的拦截记录先判定，不丢弃
        if pending is not None:
            return pending, None
        started = self.t.sequence()
        self._expected_url = self._action_url = url     # 本次动作绑定的地址：自己这一跳不记进观察诊断
        try:
            reply = self.t.navigate(url)
        except Exception:                               # noqa: BLE001 — 传输异常一律按未知停止
            return PageResult("unknown", "cdp_error"), None
        finally:
            self._expected_url = None                   # 文档建立后不再接受新的主文档
        early = self._blocked_result()
        if early is not None:
            return early, None
        exp0 = ActionExpectation(f"a{next(self._ids)}", self.t.session_id, self.t.frame_id, None, "", "", 0, {}, started)
        try:
            exp = bind_navigation_result(exp0, reply)
        except ValueError:
            return PageResult("unknown", "navigation_failed"), None
        if not self._doc_ok(exp, url):
            return self._landing_failure("document_mismatch"), None
        return None, exp

    def _doc_ok(self, exp: ActionExpectation, url: str | None) -> bool:
        doc = self.t.document()
        return (doc.get("frame_id") == exp.frame_id and doc.get("loader_id") == exp.loader_id
                and same_document(str(doc.get("url") or ""), url))

    def _landing_failure(self, reason: str) -> PageResult:
        """读当前落点再判定：登录页即未登录，验证页与平台握手家族页即风控，其余沿用传入原因。
        落点地址脱敏后记进本次动作的诊断——导航被放行、页面却自己换了地址时，这是离线唯一的线索。"""
        try:
            landed = str(self.t.document().get("url") or "")
        except Exception:                               # noqa: BLE001 — 读不到当前文档按未知处理
            return PageResult("unknown", reason)
        if len(self._notes) < MAX_DOCUMENT_NOTES:
            self._notes.append(f"landing:{redact_url(landed)}")
        state = _site_state(landed)
        if state == "login":
            return PageResult("unauthenticated", "login_page")
        if state == "security":
            return PageResult("blocked", "risk_page")
        if state == "site" and HANDSHAKE_PATH.match(urlsplit(landed).path):
            return PageResult("blocked", "handshake_not_finished")
        return PageResult("unknown", reason)

    def _capture_note(self, mismatch: str, exp: ActionExpectation, cap, classified: Classified) -> None:
        """被丢弃的响应记三条脱敏诊断：脱敏地址（只留主机、路径与参数名）、参数逐项判定、响应结构摘要。
        结构摘要分清"平台照常给数据、只是绑定失效"与"页面被限制、根本没给数据"；三条都不含参数值与岗位内容。"""
        if len(self._notes) >= MAX_DOCUMENT_NOTES:
            return
        self._notes.append(f"capture:{mismatch}:{redact_url(cap.url)}")
        if mismatch == "other_parameters" and len(self._notes) < MAX_DOCUMENT_NOTES:
            detail = parameter_mismatch(exp, cap)
            if detail:
                self._notes.append("params:" + ",".join(detail))
        if len(self._notes) < MAX_DOCUMENT_NOTES:
            self._notes.append(body_note(classified))

    def _collect(self, exp: ActionExpectation, doc_url: str) -> PageResult:
        """认领本次动作的响应。每轮开始与每个返回点都先取拦截记录：风控 > 未登录 > 超时、未知与成功。
        被丢弃的响应按固定原因码计数：离线据此分清接口没发出、端点变了、参数变了还是文档换了。"""
        deadline = self.monotonic() + self.capture_timeout
        ignored: dict[str, int] = {}

        def discard(code: str) -> None:
            ignored[code] = ignored.get(code, 0) + 1

        def tally(result: PageResult) -> PageResult:
            return replace(result, ignored_responses=sum(ignored.values()), ignored_reasons=dict(sorted(ignored.items())))

        def settle(result: PageResult) -> PageResult:
            late = self._blocked_result()
            return tally(late if late is not None else result)

        while True:
            early = self._blocked_result()
            if early is not None:
                return tally(early)
            remaining = deadline - self.monotonic()
            if remaining <= 0:
                return settle(self._landing_failure("capture_timeout"))
            try:
                batch = self.t.captures(remaining)
            except Exception:                           # noqa: BLE001
                return settle(PageResult("unknown", "cdp_error"))
            if not batch:
                return settle(self._landing_failure("capture_timeout"))
            for cap in sorted(batch, key=lambda c: c.request_sequence):
                if cap.session_id != self.t.session_id:
                    discard("other_session")
                    continue
                if cap.error_text:
                    reason = "body_unavailable" if cap.error_text == "body_unavailable" else "load_failed"
                    return settle(PageResult("unknown", reason))
                c = classify_body(cap.body, cap.http_status)
                if c.kind == "blocked":                 # 本受控会话的风险响应优先，不论是否匹配
                    return tally(PageResult("blocked", c.reason, c, cap.request_id, c.code))
                mismatch = match_failure(exp, cap)
                if mismatch == "other_document" and self._settled_onto(exp, doc_url):
                    exp = replace(exp, loader_id=str(self.t.document().get("loader_id") or ""))
                    self._last = exp                    # 翻页要接着用重新绑定后的文档
                    mismatch = match_failure(exp, cap)
                if mismatch is not None:
                    discard(mismatch)
                    self._capture_note(mismatch, exp, cap, c)
                    continue
                if not self._doc_ok(exp, doc_url):
                    return settle(self._landing_failure("document_changed"))
                if not parameters_verified(exp, cap) and len(self._notes) < MAX_DOCUMENT_NOTES:
                    self._notes.append("bound:document_only")   # 地址上没有可核对的搜索参数，只靠文档与顺序绑定
                return settle(PageResult(c.kind, c.reason, c, cap.request_id, c.code))

    # ---- 列表 ----
    def search_page(self, keyword: str, city_code: str, page: int, filters: dict) -> PageResult:
        self._begin()
        url = build_search_url(keyword, city_code, page, filters)
        early, exp = self._navigate(url)
        if early is not None:
            return self._fill(early)
        self.t.set_document_guard(False)                # 列表页提交且落点复核通过之后只旁听：逐个暂停文档请求会打断平台的令牌握手
        exp = replace(exp, keyword=keyword, city_code=city_code, page=page, canonical_filters=dict(filters))
        self._last, self._last_url = exp, url
        return self._fill(self._collect(exp, url))

    def next_page(self, page: int) -> PageResult:
        if self._last is None:
            raise RuntimeError("next_page() requires a previous search_page()")
        self._begin()
        self._action_url = self._last_url               # 翻页沿用上一页的地址判断观察记录
        pending = self._blocked_result()                # 不丢弃上一页之后到达的拦截记录
        if pending is not None:
            return self._fill(pending)
        exp = replace(self._last, action_id=f"a{next(self._ids)}", page=page, started_sequence=self.t.sequence())
        try:
            self.t.scroll_bottom()
        except Exception:                               # noqa: BLE001
            late = self._blocked_result()
            return self._fill(late if late is not None else PageResult("unknown", "cdp_error"))
        early = self._blocked_result()
        if early is not None:
            return self._fill(early)
        if not self._doc_ok(exp, self._last_url):
            return self._fill(self._landing_failure("document_changed"))
        self._last = exp
        return self._fill(self._collect(exp, self._last_url))

    # ---- 详情 / 公司 ----
    def open_job_detail(self, source_job_id: str) -> DetailRead:
        if not isinstance(source_job_id, str) or not SOURCE_ID.fullmatch(source_job_id):
            raise NavigationRefused("invalid job id")
        return self._read_page(f"https://www.zhipin.com/job_detail/{source_job_id}.html")

    def open_company(self, source_company_id: str) -> DetailRead:
        if not isinstance(source_company_id, str) or not SOURCE_ID.fullmatch(source_company_id):
            raise NavigationRefused("invalid company id")
        return self._read_page(f"https://www.zhipin.com/gongsi/{source_company_id}.html")

    def _detail_blocked(self) -> DetailRead | None:
        late = self._blocked_result()
        return DetailRead(late.kind, late.reason) if late is not None else None

    def _read_page(self, url: str) -> DetailRead:
        self._begin()
        early, exp = self._navigate(url)
        if early is not None:
            return self._fill(DetailRead(early.kind, early.reason))
        try:
            a = _json_obj(self.t.evaluate(EXTRACT_DETAIL_JS))
        except Exception:                               # noqa: BLE001
            return self._fill(self._detail_blocked() or DetailRead("unknown", "cdp_error"))
        late = self._detail_blocked()                   # 第一次读取期间出现的主文档
        if late is not None:
            return self._fill(late)
        try:
            b = _json_obj(self.t.evaluate(EXTRACT_PAGE_JS))
        except Exception:                               # noqa: BLE001
            return self._fill(self._detail_blocked() or DetailRead("unknown", "cdp_error"))
        late = self._detail_blocked()                   # 第二次读取期间出现的主文档
        if late is not None:
            return self._fill(late)
        if a is None or b is None:
            return self._fill(DetailRead("unknown", "evaluate_failed"))
        if (not same_document(str(a.get("url") or ""), url) or not same_document(str(b.get("url") or ""), url)
                or not self._doc_ok(exp, url)):
            landing = self._landing_failure("snapshot_url_mismatch")
            return self._fill(DetailRead(landing.kind, landing.reason))
        jd = str(a.get("jd") or "")
        page_text = str(b.get("page_text") or "")[:MAX_PAGE_TEXT]
        diagnostic = jd + "\n" + page_text
        if DETAIL_LOGIN_MARKER in diagnostic:
            return self._fill(DetailRead("unauthenticated", "login_wall"))
        if page_text_risk(diagnostic):
            return self._fill(DetailRead("blocked", "risk_page"))
        return self._fill(DetailRead("ok", "ok", {"jd": jd, "tags": [t for t in (a.get("tags") or []) if isinstance(t, str)],
                                                  "page_text": page_text, "text_truncated": b.get("text_truncated") is True,
                                                  "ldjson": [x for x in (b.get("ldjson") or []) if isinstance(x, str)], "url": url}))
