import json
import pytest
from tests.conftest import load_fixture
from tests.helpers.fake_transport import FakeTransport
from tests.helpers.sleeper import Sleeper
from where_my_job.errors import Blocked, EnvError
from where_my_job.launcher.chrome import BrowserState, VerifiedBrowser
from where_my_job.policy.ledger import Ledger
from where_my_job.service import browser as browser_svc
from where_my_job.store import db

pytestmark = pytest.mark.usefixtures("online_adapter_enabled")

VB = VerifiedBrowser(BrowserState(pid=4242, create_time=1000.0, exe="/x", profile="/p", port=9222,
                                  started_at="2026-09-14T12:00:00.000000Z"), "ws://127.0.0.1:9222/devtools/browser/abc")

class FakeLauncher:
    def __init__(self, verify_error=None):
        self.started = self.stopped = 0
        self.verify_error = verify_error
    def start(self):
        self.started += 1
        return VB
    def verify(self):
        if self.verify_error:
            raise self.verify_error
        return VB
    def blank_check(self, verified, allow_target_id=None):
        return None
    def stop(self):
        self.stopped += 1
        return {"stopped": True, "pid": 4242}

@pytest.fixture
def online(ctx, monkeypatch):
    box = {"made": 0}
    def install(script, launcher=None):
        t = FakeTransport(script)
        def make(c, verified):
            box["made"] += 1
            return t
        monkeypatch.setattr(browser_svc, "make_transport", make)
        monkeypatch.setattr(browser_svc, "make_pacing", lambda c: (Sleeper(ctx.clock), lambda lo, hi: lo))
        monkeypatch.setattr(browser_svc, "make_launcher", lambda lay: launcher or FakeLauncher())
        box["t"] = t
        return t
    return install, box

def test_start_browser_does_not_navigate_or_use_budget(ctx):
    fl = FakeLauncher()
    data = browser_svc.start_browser(ctx, launcher=fl)
    assert fl.started == 1 and data["browser"]["pid"] == 4242 and data["browser"]["login"] == "manual"
    assert ctx.conn.execute("select count(*) from network_policy_state").fetchone()[0] == 0

def test_probe_consumes_one_probe_action(ctx, online):
    install, _ = online
    t = install([("joblist", load_fixture("api/page1_ok.json"))])
    data, run_id = browser_svc.probe(ctx)
    assert data["probe"] == {"kind": "success", "login": "available", "has_more": True, "item_count": 2}
    assert len(t.navigations) == 1 and t.closed
    kinds = [e["kind"] for e in Ledger(ctx.conn, ctx.clock, ctx.home).view().entries]
    assert kinds == ["probe"]
    cfg = json.loads(ctx.conn.execute("select config_json from runs where run_id=?", (run_id,)).fetchone()[0])
    row = ctx.conn.execute("select kind, status from runs where run_id=?", (run_id,)).fetchone()
    assert cfg["probe"] is True and tuple(row) == ("scan", "ok")
    assert "SYN-SECURITY" not in json.dumps(data)

def test_probe_blocked_sets_cooldown_exit_3_with_run_id(ctx, online):
    install, _ = online
    install([("joblist", load_fixture("api/page2_code37.json"))])
    with pytest.raises(Blocked) as ei:
        browser_svc.probe(ctx)
    assert ei.value.code == "RISK_DETECTED" and ei.value.run_id
    assert Ledger(ctx.conn, ctx.clock, ctx.home).cooldown_until() is not None

def test_probe_in_cooldown_refused_before_run_and_transport(ctx, online):
    install, box = online
    install([("joblist", load_fixture("api/page1_ok.json"))])
    with db.write_tx(ctx.conn):
        Ledger(ctx.conn, ctx.clock, ctx.home).set_cooldown("risk_response", platform_code=31)
    with pytest.raises(Blocked) as ei:
        browser_svc.probe(ctx)
    assert ei.value.code == "COOLDOWN_ACTIVE" and ei.value.run_id is None and box["made"] == 0
    assert ctx.conn.execute("select count(*) from runs").fetchone()[0] == 0

def test_probe_unauthenticated_exit_2_no_cooldown(ctx, online):
    install, _ = online
    install([("joblist", load_fixture("api/unauthenticated.json"))])
    with pytest.raises(EnvError) as ei:
        browser_svc.probe(ctx)
    assert ei.value.code == "UNAUTHENTICATED" and ei.value.run_id
    assert Ledger(ctx.conn, ctx.clock, ctx.home).cooldown_until() is None

def test_probe_refuses_unverified_browser_before_budget(ctx, online):
    install, box = online
    install([], launcher=FakeLauncher(verify_error=EnvError("CDP_NOT_LOOPBACK", "专用浏览器调试入口不是本机回环监听，已拒绝连接")))
    with pytest.raises(EnvError) as ei:
        browser_svc.probe(ctx)
    assert ei.value.code == "CDP_NOT_LOOPBACK" and box["made"] == 0
    assert ctx.conn.execute("select count(*) from network_policy_state").fetchone()[0] == 0

def test_status_excludes_probe_from_last_scan(cli, monkeypatch, clock):
    t = FakeTransport([("joblist", load_fixture("api/empty_ok.json"))])
    monkeypatch.setattr(browser_svc, "make_launcher", lambda lay: FakeLauncher())
    monkeypatch.setattr(browser_svc, "make_transport", lambda c, v: t)
    monkeypatch.setattr(browser_svc, "make_pacing", lambda c: (Sleeper(clock), lambda lo, hi: lo))
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 0 and env["run_id"].startswith("run_") and env["data"]["probe"]["kind"] == "empty"
    rc, env, _ = cli(["status"])
    assert env["data"]["runs"]["last_scan"] is None and env["data"]["runs"]["last_probe"]["status"] == "ok"

def test_cli_init_browser_and_browser_stop(cli, monkeypatch):
    fl = FakeLauncher()
    monkeypatch.setattr(browser_svc, "make_launcher", lambda lay: fl)
    rc, env, _ = cli(["init", "--browser"])
    assert rc == 0 and env["data"]["browser"]["pid"] == 4242 and env["run_id"] is None
    rc, env, _ = cli(["browser", "stop"])
    assert rc == 0 and env["data"] == {"stopped": True, "pid": 4242} and fl.stopped == 1
