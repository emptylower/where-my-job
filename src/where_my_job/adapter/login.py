# src/where_my_job/adapter/login.py
"""扫码登录的页面侧操作：让专用 Chrome 打开固定登录页，识别页面上的二维码，观察页面自己完成登录。
不读取 Cookie，不发起任何自有请求，不保存、不输出二维码内容；二维码只以字节形式交回调用方。"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Callable
from ..errors import WmjError
from .classify import page_text_risk
from .qr import find_qr_codes, payload_digest
from .session import _site_state as site_state
from .transport import DocumentDecision, Transport

LOGIN_URL = "https://www.zhipin.com/web/user/"
POLL_SEC = 1.0
TOGGLE_AFTER_SEC = 4.0
MAX_TOGGLES = 2
REFRESH_SETTLE_SEC = 6.0
# 只保留明确说二维码本身失效的文案："点击刷新"这类按钮文案页面常驻，不能作为失效依据
EXPIRED_MARKERS = ("二维码已失效", "二维码失效", "二维码已过期", "二维码过期")
TOGGLE_KEYS = ("扫码登录", "APP扫码", "App扫码", "二维码登录", "qrcode", "ewm")
REFRESH_KEYS = ("点击刷新", "刷新二维码", "刷新")

# 只读页面地址与可见文本（用于风控文本判断与二维码过期判断），不发请求。
PAGE_STATE_JS = """
(function(){
  var text = document.body ? document.body.innerText : '';
  return JSON.stringify({url: location.href, text: text.substring(0, 4000)});
})()
"""

def click_text_js(keys: tuple[str, ...]) -> str:
    """点击文字、title、alt 或 class 含关键词的最小可见元素：等同用户点击，不发自有请求。"""
    return """
(function(keys){
  var best = null, bestArea = Infinity;
  var nodes = document.querySelectorAll('a,button,span,div,p,i,img,li,canvas');
  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    var label = [el.innerText || '', el.getAttribute('title') || '', el.getAttribute('alt') || '',
                 el.getAttribute('class') || ''].join(' ');
    var hit = false;
    for (var k = 0; k < keys.length; k++) { if (label.indexOf(keys[k]) !== -1) { hit = true; break; } }
    if (!hit) continue;
    var r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    if (r.width * r.height < bestArea) { best = el; bestArea = r.width * r.height; }
  }
  if (!best) return 'none';
  best.click();
  return 'clicked';
})(%s)
""" % json.dumps(list(keys), ensure_ascii=False)

@dataclass(frozen=True)
class LoginObservation:
    state: str                                          # qr | waiting | logged_in | expired | blocked | unknown
    reason: str                                         # 固定内部原因码
    payload: bytes | None = field(default=None, repr=False)   # 仅 state=qr；调用方写成 PNG 后丢弃
    toggles: int = 0
    refreshed: bool = False
    screenshot_failures: int = 0
    expiry_marker: str | None = None                    # 命中的失效文案（本工具自己的常量，不含页面内容）

def _json_obj(raw) -> dict:
    try:
        obj = json.loads(raw) if isinstance(raw, str) else None
    except ValueError:
        return {}
    return obj if isinstance(obj, dict) else {}

def decide_document(url: str, is_main_frame: bool) -> DocumentDecision:
    """登录期间放行同站登录页与站内页；安全验证页记为风控；站外文档一律拒绝。"""
    site = site_state(url)
    if site == "security":
        return DocumentDecision(False, "blocked")
    if site in ("login", "site"):
        return DocumentDecision(True, "ok")
    return DocumentDecision(False, "unknown")

class LoginPage:
    def __init__(self, transport: Transport, *, monotonic: Callable[[], float]):
        self.t = transport
        self.monotonic = monotonic
        self.window_raised = False                  # 是否成功把登录标签页与窗口提到前台
        transport.set_document_policy(decide_document)
        transport.set_document_guard(True)              # 登录全程拦截：没有时序敏感的握手，且要挡住风控跳转

    def activate(self) -> bool:
        """把登录标签页与窗口提到前台。只在"该让用户去扫"的时刻调用（login start、显式重画二维码），
        status 轮询期间不调用——每 30 秒抢一次焦点比看不见二维码更难用。"""
        self.window_raised = bool(self.t.activate())
        return self.window_raised

    def _risk_blocked(self) -> bool:
        return any(state == "blocked" for _, state, _main in self.t.take_blocked_documents())

    def open(self) -> LoginObservation | None:
        """导航到固定登录地址。返回 None 表示登录页已开始加载；否则返回终止观察。"""
        try:
            reply = self.t.navigate(LOGIN_URL)
        except WmjError:
            raise
        except Exception:                               # noqa: BLE001 — 传输异常一律按未知停止
            return LoginObservation("unknown", "cdp_error")
        if self._risk_blocked():
            return LoginObservation("blocked", "risk_redirect")
        result = reply.get("result") if isinstance(reply, dict) else None
        if not isinstance(result, dict) or reply.get("error") is not None or result.get("errorText"):
            return LoginObservation("unknown", "navigation_failed")
        self.activate()                             # 扫码面是浏览器窗口：导航成功就立刻让用户看得见
        return None

    def observe(self, *, wait: float, known_digest: str | None, allow_toggle: bool,
                refresh: Callable[[], bool] | None, report_current: bool = False) -> LoginObservation:
        """最多观察 wait 秒。出现新二维码、登录完成、风控、过期且不允许刷新时提前返回。
        refresh 由调用方提供：返回 True 表示已预占一次动作、可以点击刷新；额度不足时由它抛出 Blocked。
        report_current=True 时，识别到的二维码即使与 known_digest 相同也立即返回，用于重新画出当前二维码。"""
        start = self.monotonic()
        toggles, failures, refreshed, last_refresh, marker = 0, 0, False, None, None
        while True:
            try:
                if self._risk_blocked():
                    return LoginObservation("blocked", "risk_redirect", toggles=toggles, refreshed=refreshed)
                page = _json_obj(self.t.evaluate(PAGE_STATE_JS))
                url = page.get("url") if isinstance(page.get("url"), str) else self.t.document().get("url", "")
                text = page.get("text") if isinstance(page.get("text"), str) else ""
                site = site_state(url)
                if site == "security" or (site == "login" and page_text_risk(text)):
                    reason = "risk_redirect" if site == "security" else "risk_page"
                    return LoginObservation("blocked", reason, toggles=toggles, refreshed=refreshed)
                if site == "site":
                    return LoginObservation("logged_in", "left_login_page", toggles=toggles, refreshed=refreshed)
                if site == "login":
                    now = self.monotonic()
                    png = self.t.screenshot()
                    if png is None:
                        failures += 1
                    hits = find_qr_codes(png) if png else []
                    if hits and (report_current or payload_digest(hits[0].payload) != known_digest):
                        return LoginObservation("qr", "qr_found", payload=hits[0].payload, toggles=toggles,
                                                refreshed=refreshed, screenshot_failures=failures, expiry_marker=marker)
                    # 页面上已经没有可识别的二维码，且明确写着二维码失效，才点刷新：
                    # 页面自己换码时本工具不介入，避免把用户正在扫的码换掉
                    hit = next((m for m in EXPIRED_MARKERS if m in text), None) if known_digest is not None else None
                    if hit is not None and not hits:
                        marker = marker or hit
                        if last_refresh is None or now - last_refresh >= REFRESH_SETTLE_SEC:
                            if refresh is None or not refresh():
                                return LoginObservation("expired", "qr_expired", toggles=toggles, refreshed=refreshed,
                                                        expiry_marker=marker)
                            self.t.evaluate(click_text_js(REFRESH_KEYS))
                            last_refresh, refreshed = now, True
                    if (not hits and allow_toggle and known_digest is None and toggles < MAX_TOGGLES
                            and now - start >= TOGGLE_AFTER_SEC * (toggles + 1)):
                        self.t.evaluate(click_text_js(TOGGLE_KEYS))
                        toggles += 1
                if self.monotonic() - start >= wait:
                    return LoginObservation("waiting", "no_change", toggles=toggles, refreshed=refreshed,
                                            screenshot_failures=failures, expiry_marker=marker)
                self.t.idle(POLL_SEC)
            except WmjError:
                raise
            except Exception:                           # noqa: BLE001 — 传输异常一律按未知停止
                return LoginObservation("unknown", "cdp_error", toggles=toggles, refreshed=refreshed)
