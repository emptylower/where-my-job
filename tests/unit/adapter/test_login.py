# tests/unit/adapter/test_login.py
import pytest
from tests.helpers.fake_login_transport import FakeLoginTransport
from where_my_job.adapter import login
from where_my_job.adapter.qr import payload_digest
from where_my_job.errors import Blocked

LOGIN = "https://www.zhipin.com/web/user/"
SITE = "https://www.zhipin.com/web/geek/job-recommend"
SECURITY = "https://www.zhipin.com/web/common/security-check.html"
A = b"https://example.invalid/login?uuid=SYN-LOGIN-A"
B = b"https://example.invalid/login?uuid=SYN-LOGIN-B"
DOWNLOAD = b"https://example.invalid/app?from=SYN-DOWNLOAD"
EXPIRED = "二维码已失效，点击刷新"

def _start(t, wait=20.0):
    page = login.LoginPage(t, monotonic=t.clock.monotonic)
    assert page.open() is None
    return page, page.observe(wait=wait, known_digest=None, allow_toggle=True, refresh=None)

def test_start_returns_largest_code_and_navigates_only_login_url(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A, "small_qr": DOWNLOAD}], clock=clock)
    _, obs = _start(t)
    assert obs.state == "qr" and obs.payload == A
    assert t.navigations == [login.LOGIN_URL] and t.clicks == []

def test_observation_repr_hides_payload(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A}], clock=clock)
    _, obs = _start(t)
    assert "SYN-LOGIN-A" not in repr(obs)

def test_no_code_visible_clicks_scan_toggle_then_finds_code(clock):
    t = FakeLoginTransport([{"url": LOGIN}] * 6 + [{"url": LOGIN, "qr": A}], clock=clock)
    _, obs = _start(t)
    assert obs.state == "qr" and obs.payload == A and obs.toggles == 1 and t.clicks == ["toggle"]

def test_no_code_within_wait_reports_waiting_after_two_toggles(clock):
    t = FakeLoginTransport([{"url": LOGIN}], clock=clock)
    _, obs = _start(t, wait=20.0)
    assert obs.state == "waiting" and obs.payload is None and t.clicks == ["toggle", "toggle"]

def test_already_logged_in_redirect_is_reported_without_screenshot(clock):
    t = FakeLoginTransport([{"url": SITE}], clock=clock)
    _, obs = _start(t)
    assert obs.state == "logged_in" and t.screenshots == 0

def test_security_redirect_on_open_is_blocked(clock):
    t = FakeLoginTransport([{"url": SECURITY}], clock=clock)
    obs = login.LoginPage(t, monotonic=clock.monotonic).open()
    assert obs.state == "blocked" and obs.reason == "risk_redirect" and t.url == "about:blank"

def test_risk_text_on_login_page_is_blocked(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A, "text": "请完成验证后继续"}], clock=clock)
    _, obs = _start(t)
    assert obs.state == "blocked" and obs.reason == "risk_page"

def test_status_waits_on_same_code_then_confirms(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A}, {"url": LOGIN, "qr": A}, {"url": SITE}], clock=clock)
    page, first = _start(t)
    obs = page.observe(wait=30.0, known_digest=payload_digest(first.payload), allow_toggle=False, refresh=None)
    assert obs.state == "logged_in"

def test_status_returns_new_code_when_page_rotates_it(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A}, {"url": LOGIN, "qr": B}], clock=clock)
    page, _ = _start(t)
    obs = page.observe(wait=30.0, known_digest=payload_digest(A), allow_toggle=False, refresh=None)
    assert obs.state == "qr" and obs.payload == B

def test_status_wait_elapses_without_change(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A}], clock=clock)
    page, _ = _start(t)
    before = clock.monotonic()
    obs = page.observe(wait=5.0, known_digest=payload_digest(A), allow_toggle=False, refresh=None)
    assert obs.state == "waiting" and clock.monotonic() - before >= 5.0

def test_expired_code_refresh_when_permitted_then_new_code(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A}, {"url": LOGIN, "text": EXPIRED},
                            {"url": LOGIN, "qr": B}], clock=clock)
    page, _ = _start(t)
    calls = []
    def refresh():
        calls.append(1)
        return True
    obs = page.observe(wait=30.0, known_digest=payload_digest(A), allow_toggle=False, refresh=refresh)
    assert obs.state == "qr" and obs.payload == B and obs.refreshed
    assert calls == [1] and t.clicks == ["refresh"]

def test_expired_code_without_permission_reports_expired(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A}, {"url": LOGIN, "text": EXPIRED}], clock=clock)
    page, _ = _start(t)
    obs = page.observe(wait=30.0, known_digest=payload_digest(A), allow_toggle=False, refresh=lambda: False)
    assert obs.state == "expired" and t.clicks == []

def test_refresh_budget_refusal_propagates(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A}, {"url": LOGIN, "text": EXPIRED}], clock=clock)
    page, _ = _start(t)
    def refresh():
        raise Blocked("BUDGET_EXHAUSTED", "本次计划超过可用动作额度")
    with pytest.raises(Blocked):
        page.observe(wait=30.0, known_digest=payload_digest(A), allow_toggle=False, refresh=refresh)

def test_offsite_document_is_refused_and_login_continues(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A}, {"url": "https://evil.example/landing"}, {"url": SITE}], clock=clock)
    page, _ = _start(t)
    obs = page.observe(wait=30.0, known_digest=payload_digest(A), allow_toggle=False, refresh=None)
    assert obs.state == "logged_in" and "https://evil.example/landing" not in t.visited

def test_screenshot_failures_are_counted(clock):
    t = FakeLoginTransport([{"url": LOGIN, "screenshot": False}], clock=clock)
    _, obs = _start(t, wait=3.0)
    assert obs.state == "waiting" and obs.screenshot_failures >= 3

def test_transport_error_is_unknown(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A}], clock=clock, eval_error=True)
    page = login.LoginPage(t, monotonic=clock.monotonic)
    assert page.open() is None
    assert page.observe(wait=5.0, known_digest=None, allow_toggle=True, refresh=None).state == "unknown"

def test_report_current_returns_the_same_code_for_redisplay(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A}], clock=clock)
    page, _ = _start(t)
    obs = page.observe(wait=0.0, known_digest=payload_digest(A), allow_toggle=False, refresh=None, report_current=True)
    assert obs.state == "qr" and obs.payload == A and t.clicks == []

def test_valid_code_is_not_refreshed_while_waiting(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A}], clock=clock)
    page, _ = _start(t)
    calls = []
    def refresh():
        calls.append(1)
        return True
    obs = page.observe(wait=30.0, known_digest=payload_digest(A), allow_toggle=False, refresh=refresh)
    assert obs.state == "waiting" and calls == [] and t.clicks == []

def test_page_that_still_shows_a_code_is_never_refreshed(clock):
    """页面上还有可识别的二维码时，即使出现"点击刷新"之类按钮文案也不刷新。"""
    t = FakeLoginTransport([{"url": LOGIN, "qr": A, "text": "二维码已失效，点击刷新"}], clock=clock)
    page, _ = _start(t)
    calls = []
    obs = page.observe(wait=20.0, known_digest=payload_digest(A), allow_toggle=False,
                       refresh=lambda: calls.append(1) or True)
    assert obs.state == "waiting" and calls == [] and t.clicks == []

def test_refresh_needs_both_no_code_and_an_expiry_marker(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A},
                            {"url": LOGIN, "text": "二维码已失效，点击刷新"},
                            {"url": LOGIN, "qr": B}], clock=clock)
    page, _ = _start(t)
    obs = page.observe(wait=30.0, known_digest=payload_digest(A), allow_toggle=False, refresh=lambda: True)
    assert obs.state == "qr" and obs.payload == B and obs.refreshed and t.clicks == ["refresh"]
    assert obs.expiry_marker == "二维码已失效"

def test_blank_page_without_expiry_marker_is_not_refreshed(clock):
    t = FakeLoginTransport([{"url": LOGIN, "qr": A}, {"url": LOGIN, "text": "正在加载"}], clock=clock)
    page, _ = _start(t)
    calls = []
    obs = page.observe(wait=10.0, known_digest=payload_digest(A), allow_toggle=False,
                       refresh=lambda: calls.append(1) or True)
    assert obs.state == "waiting" and calls == [] and t.clicks == []

def test_login_keeps_the_document_guard_on(clock):
    """登录全程保持文档拦截：这条链路没有时序敏感的握手，且要挡住风控跳转。"""
    t = FakeLoginTransport([], clock=clock)
    login.LoginPage(t, monotonic=clock.monotonic)
    assert t.guard is True
