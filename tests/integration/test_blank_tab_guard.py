"""专用浏览器里有别的标签页时：退出 2、独立错误码、不建 run、不占额度、地址已脱敏。"""
import pytest
from tests.helpers.sleeper import Sleeper
from where_my_job.browser_pages import not_blank_error
from where_my_job.launcher.chrome import BrowserState, VerifiedBrowser
from where_my_job.policy.ledger import Ledger
from where_my_job.service import browser as browser_svc

pytestmark = pytest.mark.usefixtures("online_adapter_enabled")

VB = VerifiedBrowser(BrowserState(pid=4242, create_time=1000.0, exe="/x", profile="/p", port=9222,
                                  started_at="2026-09-14T12:00:00.000000Z"), "ws://127.0.0.1:9222/devtools/browser/abc")
STRAY = [{"type": "page", "url": "https://www.zhipin.com/?ka=header", "id": "T9"}]

class StrayTabLauncher:
    def __init__(self):
        self.verified = 0
    def start(self):
        return VB
    def verify(self):
        self.verified += 1
        return VB
    def blank_check(self, verified, allow_target_id=None):
        assert verified is VB
        raise not_blank_error(STRAY)

@pytest.fixture
def stray(monkeypatch, clock):
    box = {"made": 0}
    def forbidden(ctx, verified):
        box["made"] += 1
        raise AssertionError("transport must not be opened when the browser has stray tabs")
    monkeypatch.setattr(browser_svc, "make_transport", forbidden)
    monkeypatch.setattr(browser_svc, "make_launcher", lambda lay: StrayTabLauncher())
    monkeypatch.setattr(browser_svc, "make_pacing", lambda ctx: (Sleeper(clock), lambda lo, hi: lo))
    return box

def test_probe_refuses_before_run_and_budget(cli, wmj_home, clock, stray):
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 2 and env["errors"][0]["code"] == "BROWSER_NOT_BLANK"
    assert env["run_id"] is None and stray["made"] == 0
    assert env["data"]["browser"]["open_pages"] == ["https://www.zhipin.com/?[ka]"]
    assert "browser stop" in env["data"]["browser"]["next_step"]
    from where_my_job.store import db
    c = db.open_db(wmj_home.db_path, clock=clock)
    try:
        assert c.execute("select count(*) from runs").fetchone()[0] == 0
        assert not Ledger(c, clock, wmj_home).view().entries
    finally:
        c.close()
