# tests/integration/test_login_cmd.py
import io, json, stat
import pytest
from tests.helpers.fake_login_transport import FakeLoginTransport
from tests.helpers.qr_text import decode_lines, drawings
from tests.helpers.sleeper import Sleeper
from where_my_job.errors import EnvError
from where_my_job.launcher.chrome import BrowserState, VerifiedBrowser
from where_my_job.policy.ledger import Ledger
from where_my_job.public_messages import public_message
from where_my_job.service import login as login_svc
from where_my_job.store import db

pytestmark = pytest.mark.usefixtures("online_adapter_enabled")

LOGIN = "https://www.zhipin.com/web/user/"
SITE = "https://www.zhipin.com/web/geek/job-recommend"
SECURITY = "https://www.zhipin.com/web/common/security-check.html"
A = b"https://example.invalid/login?uuid=SYN-LOGIN-A"
B = b"https://example.invalid/login?uuid=SYN-LOGIN-B"
EXPIRED = "二维码已失效，点击刷新"
CAPTION = login_svc.QR_CAPTION
VB = VerifiedBrowser(BrowserState(pid=4242, create_time=1000.0, exe="/x", profile="/p", port=9222,
                                  started_at="2026-09-14T12:00:00.000000Z"), "ws://127.0.0.1:9222/devtools/browser/abc")

class FakeLauncher:
    def __init__(self):
        self.started = 0
        self.verified = 0
    def start(self):
        self.started += 1
        return VB
    def verify(self):
        self.verified += 1
        return VB
    def blank_check(self, verified, allow_target_id=None):
        return None

@pytest.fixture
def fake(monkeypatch, clock):
    box = {"new": 0, "attach": 0, "launcher": FakeLauncher()}
    def install(pages):
        t = FakeLoginTransport(pages, clock=clock)
        def make(ctx, verified):
            box["new"] += 1
            return t
        def attach(ctx, verified, target_id):
            box["attach"] += 1
            if not t.tab_open or target_id != t.target_id:
                raise EnvError("LOGIN_NOT_STARTED", public_message("LOGIN_NOT_STARTED"))
            return t
        monkeypatch.setattr(login_svc, "make_transport", make)
        monkeypatch.setattr(login_svc, "make_attach_transport", attach)
        monkeypatch.setattr(login_svc, "make_launcher", lambda lay: box["launcher"])
        monkeypatch.setattr(login_svc, "make_pacing", lambda ctx: (Sleeper(clock), lambda lo, hi: lo))
        box["t"] = t
        return t
    return install, box

def _ledger_kinds(wmj_home, clock):
    c = db.open_db(wmj_home.db_path, clock=clock)
    try:
        return [e["kind"] for e in Ledger(c, clock, wmj_home).view().entries]
    finally:
        c.close()

def _codes(err, light_terminal=False):
    return [decode_lines(d, light_terminal=light_terminal) for d in drawings(err, CAPTION)]

def test_start_saves_png_keeps_tab_then_status_confirms(cli, wmj_home, clock, fake):
    install, _ = fake
    t = install([{"url": LOGIN, "qr": A}, {"url": LOGIN, "qr": A}, {"url": SITE}])
    rc, env, _ = cli(["login", "start"])
    assert rc == 0, env
    view = env["data"]["login"]
    png = wmj_home.state / "login-qr.png"
    assert view["status"] == "waiting_scan" and view["qr_png"] == str(png) and env["run_id"]
    assert stat.S_IMODE(png.stat().st_mode) == 0o600
    assert t.detached and not t.closed and t.navigations == [LOGIN]
    rc, env2, _ = cli(["login", "status", "--wait", "10"])
    assert rc == 0, env2
    assert env2["data"]["login"]["status"] == "confirmed" and env2["run_id"] is None
    assert t.closed and not png.exists() and not (wmj_home.state / "login.json").exists()
    assert _ledger_kinds(wmj_home, clock) == ["login"]
    c = db.open_db(wmj_home.db_path, clock=clock)
    try:
        row = c.execute("select kind, status, config_json from runs where run_id=?", (env["run_id"],)).fetchone()
    finally:
        c.close()
    assert row[0] == "scan" and row[1] == "ok" and json.loads(row[2])["login"] is True

def test_qr_is_drawn_in_stderr_as_scannable_blocks_and_never_as_text(cli, wmj_home, fake):
    install, _ = fake
    install([{"url": LOGIN, "qr": A}, {"url": LOGIN, "qr": B}])
    rc, env, err = cli(["login", "start"])
    rc2, env2, err2 = cli(["login", "status", "--wait", "5"])
    assert rc == rc2 == 0
    assert env["data"]["login"]["status"] == "waiting_scan" and env2["data"]["login"]["status"] == "qr_updated"
    assert _codes(err) == [A] and _codes(err2) == [B]
    stdout_text = json.dumps([env, env2], ensure_ascii=False)
    assert "█" not in stdout_text and "▀" not in stdout_text and "▄" not in stdout_text
    text = stdout_text + err + err2 + (wmj_home.state / "login.json").read_text(encoding="utf-8")
    raw = b""
    for suffix in ("", "-wal"):
        p = wmj_home.state / ("where-my-job.sqlite3" + suffix)
        if p.exists():
            raw += p.read_bytes()
    for secret in ("SYN-LOGIN-A", "SYN-LOGIN-B"):
        assert secret not in text and secret.encode() not in raw

def test_tty_gets_colored_drawing_and_agent_output_gets_plain_blocks(ctx):
    class Tty(io.StringIO):
        def isatty(self):
            return True
    ctx.stderr = io.StringIO()
    path = login_svc._save_qr(ctx, A)
    plain = ctx.stderr.getvalue()
    assert "\x1b" not in plain and _codes(plain) == [A]
    assert "SYN-LOGIN-A" not in plain and path.endswith("login-qr.png")
    ctx.stderr = Tty()
    login_svc._save_qr(ctx, A)
    out = ctx.stderr.getvalue()
    assert out.startswith(CAPTION + "\n") and "\x1b[30;107m" in out and "SYN-LOGIN-A" not in out

def test_light_terminal_flag_draws_for_light_background(cli, fake):
    install, _ = fake
    install([{"url": LOGIN, "qr": A}])
    rc, env, err = cli(["login", "start", "--light-terminal"])
    assert rc == 0, env
    assert _codes(err, light_terminal=True) == [A] and _codes(err) != [A]

def test_show_qr_redraws_current_code_without_refresh_or_action(cli, wmj_home, clock, fake):
    install, _ = fake
    t = install([{"url": LOGIN, "qr": A}])
    assert cli(["login", "start"])[0] == 0
    rc, env, err = cli(["login", "status", "--wait", "0", "--show-qr"])
    assert rc == 0 and env["data"]["login"]["status"] == "waiting_scan"
    assert _codes(err) == [A]
    assert t.clicks == [] and _ledger_kinds(wmj_home, clock) == ["login"]

def test_waiting_without_change_draws_nothing(cli, fake):
    install, _ = fake
    install([{"url": LOGIN, "qr": A}])
    assert cli(["login", "start"])[0] == 0
    rc, env, err = cli(["login", "status", "--wait", "3"])
    assert rc == 0 and env["data"]["login"]["status"] == "waiting_scan" and CAPTION not in err

def test_already_logged_in_closes_tab_without_state(cli, wmj_home, fake):
    install, _ = fake
    t = install([{"url": SITE}])
    rc, env, _ = cli(["login", "start"])
    assert rc == 0 and env["data"]["login"]["status"] == "already_logged_in"
    assert t.closed and not (wmj_home.state / "login.json").exists()

def test_no_code_keeps_tab_and_reports_qr_not_found(cli, wmj_home, fake):
    install, _ = fake
    t = install([{"url": LOGIN}])
    rc, env, err = cli(["login", "start"])
    assert rc == 0 and env["data"]["login"]["status"] == "qr_not_found" and env["data"]["login"]["qr_png"] is None
    assert t.detached and not t.closed and t.clicks == ["toggle", "toggle"] and CAPTION not in err
    assert (wmj_home.state / "login.json").exists()

def test_risk_text_during_start_exits_3_with_cooldown(cli, wmj_home, clock, fake):
    install, _ = fake
    t = install([{"url": LOGIN, "text": "请完成验证"}])
    rc, env, _ = cli(["login", "start"])
    assert rc == 3 and env["errors"][0]["code"] == "RISK_DETECTED" and t.closed
    c = db.open_db(wmj_home.db_path, clock=clock)
    try:
        assert Ledger(c, clock, wmj_home).cooldown_until() is not None
    finally:
        c.close()
    assert not (wmj_home.state / "login.json").exists()

def test_security_redirect_during_status_exits_3_and_clears(cli, wmj_home, fake):
    install, _ = fake
    t = install([{"url": LOGIN, "qr": A}, {"url": SECURITY}])
    assert cli(["login", "start"])[0] == 0
    rc, env, _ = cli(["login", "status", "--wait", "5"])
    assert rc == 3 and env["errors"][0]["code"] == "RISK_DETECTED"
    assert t.closed and not (wmj_home.state / "login.json").exists()

def test_expired_code_refresh_consumes_a_login_action_and_draws_the_new_code(cli, wmj_home, clock, fake):
    install, _ = fake
    install([{"url": LOGIN, "qr": A}, {"url": LOGIN, "text": EXPIRED}, {"url": LOGIN, "qr": B}])
    assert cli(["login", "start"])[0] == 0
    rc, env, err = cli(["login", "status", "--wait", "30"])
    assert rc == 0, env
    assert env["data"]["login"]["status"] == "qr_updated" and env["data"]["login"]["refreshes"] == 1
    assert _codes(err) == [B]
    assert _ledger_kinds(wmj_home, clock) == ["login", "login"]

def test_expired_until_refresh_limit_then_timeout_closes_tab(cli, wmj_home, clock, fake):
    install, _ = fake
    t = install([{"url": LOGIN, "qr": A}, {"url": LOGIN, "text": EXPIRED}])
    assert login_svc.MAX_REFRESHES == 6
    assert cli(["login", "start"])[0] == 0
    rc, env, _ = cli(["login", "status", "--wait", "90"])
    assert rc == 2 and env["errors"][0]["code"] == "LOGIN_TIMEOUT"
    assert t.clicks == ["refresh"] * login_svc.MAX_REFRESHES
    assert t.closed and not (wmj_home.state / "login.json").exists()
    assert _ledger_kinds(wmj_home, clock) == ["login"] * (1 + login_svc.MAX_REFRESHES)

def test_status_after_session_limit_times_out(cli, wmj_home, clock, fake):
    install, _ = fake
    t = install([{"url": LOGIN, "qr": A}])
    assert cli(["login", "start"])[0] == 0
    clock.advance(601)
    rc, env, _ = cli(["login", "status", "--wait", "0"])
    assert rc == 2 and env["errors"][0]["code"] == "LOGIN_TIMEOUT" and t.closed

def test_cooldown_refuses_start_before_browser_or_transport(cli, wmj_home, clock, fake):
    install, box = fake
    install([{"url": LOGIN, "qr": A}])
    assert cli(["init"])[0] == 0
    c = db.open_db(wmj_home.db_path, clock=clock)
    try:
        with db.write_tx(c):
            Ledger(c, clock, wmj_home).set_cooldown("risk_response", platform_code=31)
    finally:
        c.close()
    rc, env, _ = cli(["login", "start"])
    assert rc == 3 and env["errors"][0]["code"] == "COOLDOWN_ACTIVE"
    assert box["new"] == 0 and box["launcher"].started == 0

def test_start_again_reuses_open_login_tab_and_redraws_without_new_action(cli, wmj_home, clock, fake):
    install, box = fake
    install([{"url": LOGIN, "qr": A}])
    rc, env, _ = cli(["login", "start"])
    rc2, env2, err2 = cli(["login", "start"])
    assert rc == rc2 == 0 and box["new"] == 1 and box["attach"] == 1
    assert env2["data"]["login"]["status"] == "waiting_scan" and env2["run_id"] is None
    assert _codes(err2) == [A]
    assert _ledger_kinds(wmj_home, clock) == ["login"]

def test_status_without_session_and_with_corrupt_state(cli, wmj_home, fake):
    install, _ = fake
    install([{"url": LOGIN}])
    rc, env, _ = cli(["login", "status"])
    assert rc == 2 and env["errors"][0]["code"] == "LOGIN_NOT_STARTED"
    (wmj_home.state / "login.json").write_text("{not json", encoding="utf-8")
    rc, env, _ = cli(["login", "status"])
    assert rc == 2 and env["errors"][0]["code"] == "LOGIN_NOT_STARTED"

def test_status_wait_out_of_range_is_invalid(cli, fake):
    install, _ = fake
    install([{"url": LOGIN}])
    rc, env, _ = cli(["login", "status", "--wait", "91"])
    assert rc == 1 and env["errors"][0]["path"] == "--wait"

def test_status_when_tab_was_closed_clears_state(cli, wmj_home, fake):
    install, _ = fake
    t = install([{"url": LOGIN, "qr": A}])
    assert cli(["login", "start"])[0] == 0
    t.tab_open = False
    rc, env, _ = cli(["login", "status", "--wait", "0"])
    assert rc == 2 and env["errors"][0]["code"] == "LOGIN_NOT_STARTED"
    assert not (wmj_home.state / "login.json").exists() and not (wmj_home.state / "login-qr.png").exists()

def test_cancel_closes_tab_and_is_available_when_online_disabled(cli, wmj_home, fake, monkeypatch):
    from where_my_job import release
    install, _ = fake
    t = install([{"url": LOGIN, "qr": A}])
    assert cli(["login", "start"])[0] == 0
    monkeypatch.setattr(release, "ONLINE_ADAPTER_DEFAULT", "disabled")
    rc, env, _ = cli(["login", "cancel"])
    assert rc == 0 and env["data"] == {"login": {"cancelled": True}} and t.closed
    assert not (wmj_home.state / "login-qr.png").exists() and not (wmj_home.state / "login.json").exists()

def test_test_qr_draws_offline_without_touching_the_browser(cli, wmj_home, fake):
    install, box = fake
    install([{"url": LOGIN, "qr": A}])
    rc, env, err = cli(["login", "test-qr"])
    assert rc == 0, env
    assert env["data"]["login"] == {"status": "test_drawing", "light_terminal": False,
                                    "next_step": login_svc.NEXT_TEST_QR}
    assert box["launcher"].started == 0 and box["launcher"].verified == 0
    (drawing,) = drawings(err, login_svc.TEST_QR_CAPTION)
    assert decode_lines(drawing) == login_svc.TEST_QR_PAYLOAD
    assert not (wmj_home.state / "login-qr.png").exists()

def test_test_qr_light_terminal_flag_switches_the_drawing(cli, fake):
    install, _ = fake
    install([{"url": LOGIN, "qr": A}])
    rc, env, err = cli(["login", "test-qr", "--light-terminal"])
    assert rc == 0 and env["data"]["login"]["light_terminal"] is True
    (drawing,) = drawings(err, login_svc.TEST_QR_CAPTION)
    assert decode_lines(drawing, light_terminal=True) == login_svc.TEST_QR_PAYLOAD

def test_settings_choose_the_terminal_background_and_flags_override(cli, wmj_home, fake):
    install, _ = fake
    install([{"url": LOGIN, "qr": A}, {"url": LOGIN, "qr": A}])
    wmj_home.config("settings.json").write_text('{"schema_version": 1, "qr_terminal_background": "light"}',
                                                encoding="utf-8")
    rc, env, err = cli(["login", "start"])
    assert rc == 0, env
    (drawing,) = drawings(err, CAPTION)
    assert decode_lines(drawing, light_terminal=True) == A
    rc, env, err = cli(["login", "status", "--wait", "0", "--show-qr", "--dark-terminal"])
    assert rc == 0, env
    (drawing,) = drawings(err, CAPTION)
    assert decode_lines(drawing) == A

def test_settings_without_the_key_fall_back_to_the_dark_drawing(cli, wmj_home, fake):
    install, _ = fake
    install([{"url": LOGIN, "qr": A}])
    wmj_home.config("settings.json").write_text('{"schema_version": 1}', encoding="utf-8")
    rc, env, err = cli(["login", "start"])
    assert rc == 0, env
    (drawing,) = drawings(err, CAPTION)
    assert decode_lines(drawing) == A

def test_expiry_marker_is_reported_to_the_agent(cli, wmj_home, clock, fake):
    install, _ = fake
    install([{"url": LOGIN, "qr": A}, {"url": LOGIN, "text": EXPIRED}, {"url": LOGIN, "qr": B}])
    assert cli(["login", "start"])[0] == 0
    rc, env, _ = cli(["login", "status", "--wait", "30"])
    assert rc == 0, env
    view = env["data"]["login"]
    assert view["status"] == "qr_updated" and view["refreshes"] == 1
    assert view["notes"] == ["expiry_marker:二维码已失效"]

def test_page_text_alone_does_not_consume_a_login_action(cli, wmj_home, clock, fake):
    install, _ = fake
    t = install([{"url": LOGIN, "qr": A, "text": EXPIRED}])
    assert cli(["login", "start"])[0] == 0
    rc, env, _ = cli(["login", "status", "--wait", "5"])
    assert rc == 0 and env["data"]["login"]["status"] == "waiting_scan"
    assert env["data"]["login"]["notes"] == [] and t.clicks == []
    assert _ledger_kinds(wmj_home, clock) == ["login"]

def test_login_start_raises_the_window_and_reports_the_browser_as_the_scan_surface(cli, wmj_home, fake):
    """扫码面是浏览器窗口，不是终端输出：GUI / TUI 前端根本没有"展开命令输出"这回事。
    导航成功就把标签页与窗口提到前台，并把结果如实写进 envelope，让 agent 有机器可读依据。"""
    install, _ = fake
    t = install([{"url": LOGIN, "qr": A}])
    rc, env, err = cli(["login", "start"])
    assert rc == 0, env
    view = env["data"]["login"]
    assert view["surface"] == "browser" and view["window_raised"] is True
    assert t.activations == 1                                  # 导航成功后置前一次，不多不少
    assert "专用 Chrome 窗口" in view["next_step"]
    assert _codes(err) == [A]                                  # 字符画仍然画，作为终端界面的备用显示

def test_window_raise_failure_is_reported_not_fatal(cli, wmj_home, fake, monkeypatch):
    install, _ = fake
    t = install([{"url": LOGIN, "qr": A}])
    t.activate_fails = True
    rc, env, _ = cli(["login", "start"])
    assert rc == 0
    view = env["data"]["login"]
    assert view["status"] == "waiting_scan" and view["surface"] == "browser" and view["window_raised"] is False

def test_status_polling_does_not_steal_focus_but_show_qr_does(cli, wmj_home, fake):
    """轮询每 30 秒抢一次焦点比看不见二维码更难用：只有用户说"看不到"时才重新置前。"""
    install, _ = fake
    t = install([{"url": LOGIN, "qr": A}, {"url": LOGIN, "qr": A}, {"url": LOGIN, "qr": A}])
    assert cli(["login", "start"])[0] == 0
    assert t.activations == 1
    assert cli(["login", "status", "--wait", "0"])[0] == 0
    assert t.activations == 1                                  # 普通轮询不置前
    rc, env, _ = cli(["login", "status", "--wait", "0", "--show-qr"])
    assert rc == 0 and t.activations == 2                      # 显式重画才置前
    assert env["data"]["login"]["surface"] == "browser"
