# tests/helpers/fake_login_transport.py
"""扫码登录用传输替身。pages 是按轮询推进的页面状态序列，每项：
  {"url": str, "qr": bytes | None, "small_qr": bytes | None, "text": str, "screenshot": bool（默认 True）}
navigate() 让第 0 项经过 Document 策略后生效；每次 idle() 推进到下一项（到末尾停住）并推进时钟。
地址变化时同样经过策略：被拒绝的地址记入拦截记录，页面停在原地址。
evaluate() 识别 login.PAGE_STATE_JS 与两种点击脚本；screenshot() 生成含二维码的合成截图。"""
from __future__ import annotations
import io, json
import segno
from PIL import Image
from where_my_job.adapter import login

def page_png(qr: bytes | None, small_qr: bytes | None = None) -> bytes:
    page = Image.new("RGB", (1280, 800), (245, 246, 248))
    for payload, scale, pos in ((qr, 6, (600, 200)), (small_qr, 2, (80, 650))):
        if payload:
            buf = io.BytesIO()
            segno.make_qr(payload, error="m").save(buf, kind="png", scale=scale, border=4)
            page.paste(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"), pos)
    out = io.BytesIO()
    page.save(out, format="PNG")
    return out.getvalue()

class FakeLoginTransport:
    session_id = "S-own"
    frame_id = "F-top"

    def __init__(self, pages, *, clock, target_id: str = "T-login", eval_error: bool = False):
        self.pages = [dict(p) for p in pages]
        self.clock = clock
        self.target_id = target_id
        self.eval_error = eval_error
        self.index = -1
        self.url = "about:blank"
        self.visited: list[str] = []
        self.navigations: list[str] = []
        self.clicks: list[str] = []
        self.screenshots = 0
        self.activations = 0
        self.activate_fails = False
        self.closed = False
        self.detached = False
        self.tab_open = True
        self._policy = None
        self.guard = False
        self._blocked: list[tuple[str, str, bool]] = []
        self._png_cache: dict = {}

    def sequence(self) -> int:
        return 0

    def set_document_policy(self, policy) -> None:
        self._policy = policy

    def set_document_guard(self, on: bool) -> None:
        self.guard = on

    def take_navigations(self) -> list[str]:
        return []

    def take_blocked_documents(self) -> list[tuple[str, str, bool]]:
        out, self._blocked = self._blocked, []
        return out

    def document(self) -> dict:
        return {"url": self.url, "frame_id": self.frame_id, "loader_id": f"L{self.index}"}

    def _enter(self, i: int) -> bool:
        self.index = i
        target = self.pages[i]["url"]
        if target == self.url:
            return True
        decision = self._policy(target, True)
        if not decision.allow:
            self._blocked.append((target, decision.state, True))
            return False
        self.url = target
        self.visited.append(target)
        return True

    def _current(self) -> dict:
        return self.pages[max(self.index, 0)]

    def activate(self) -> bool:
        """真实实现调 Target.activateTarget + Page.bringToFront；置前失败不致命，返回 False。"""
        self.activations += 1
        return not self.activate_fails

    def navigate(self, url: str) -> dict:
        self.navigations.append(url)
        if not self._enter(0):
            return {"id": 1, "result": {"frameId": self.frame_id, "loaderId": "", "errorText": "net::ERR_BLOCKED_BY_CLIENT"}}
        return {"id": 1, "result": {"frameId": self.frame_id, "loaderId": "L0"}}

    def evaluate(self, js: str):
        if self.eval_error:
            raise RuntimeError("synthetic cdp failure")
        if js == login.PAGE_STATE_JS:
            return json.dumps({"url": self.url, "text": self._current().get("text", "")}, ensure_ascii=False)
        if js == login.click_text_js(login.REFRESH_KEYS):
            self.clicks.append("refresh")
            return "clicked"
        if js == login.click_text_js(login.TOGGLE_KEYS):
            self.clicks.append("toggle")
            return "clicked"
        return None

    def screenshot(self):
        self.screenshots += 1
        page = self._current()
        if page.get("screenshot", True) is False:
            return None
        key = (page.get("qr"), page.get("small_qr"))
        if key not in self._png_cache:
            self._png_cache[key] = page_png(*key)
        return self._png_cache[key]

    def idle(self, seconds: float) -> None:
        self.clock.advance(seconds)
        if self.index < len(self.pages) - 1:
            self._enter(self.index + 1)

    def detach(self) -> None:
        self.detached = True

    def close(self) -> None:
        self.closed = True
        self.tab_open = False
