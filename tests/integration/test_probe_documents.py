# tests/integration/test_probe_documents.py
"""探测在三种真实情形下的行为：站外子文档被拒、主文档带参数跳转、主文档跳到别的路径。
诊断只含脱敏地址（主机、路径、参数名），失败时也要能读到。"""
import pytest
from tests.conftest import load_fixture
from tests.helpers.fake_transport import FakeTransport
from tests.helpers.sleeper import Sleeper
from where_my_job.launcher.chrome import BrowserState, VerifiedBrowser
from where_my_job.service import browser as browser_svc
from where_my_job.store import db

pytestmark = pytest.mark.usefixtures("online_adapter_enabled")

SEARCH = "https://www.zhipin.com/web/geek/job?query=%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86&city=101220100&page=1"
VB = VerifiedBrowser(BrowserState(pid=4242, create_time=1000.0, exe="/x", profile="/p", port=9222,
                                  started_at="2026-09-14T12:00:00.000000Z"), "ws://127.0.0.1:9222/devtools/browser/abc")

class FakeLauncher:
    def start(self):
        return VB
    def verify(self):
        return VB
    def blank_check(self, verified, allow_target_id=None):
        return None

@pytest.fixture
def probe(monkeypatch, clock):
    def install(script):
        t = FakeTransport(script)
        monkeypatch.setattr(browser_svc, "make_transport", lambda ctx, verified: t)
        monkeypatch.setattr(browser_svc, "make_launcher", lambda lay: FakeLauncher())
        monkeypatch.setattr(browser_svc, "make_pacing", lambda ctx: (Sleeper(clock), lambda lo, hi: lo))
        return t
    return install

def _summary(wmj_home, clock, run_id):
    import json
    c = db.open_db(wmj_home.db_path, clock=clock)
    try:
        return json.loads(c.execute("select summary_json from runs where run_id=?", (run_id,)).fetchone()[0])
    finally:
        c.close()

def test_offsite_subframe_does_not_fail_the_probe(cli, wmj_home, clock, probe):
    t = probe([("subframe", "https://ads.example/pixel.html?uid=SECRET"), ("joblist", load_fixture("api/page1_ok.json"))])
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 0, env
    assert env["data"]["probe"]["login"] == "available"
    assert env["data"]["refused_subframes"] == 1
    assert env["data"]["documents"] == ["sub:unknown:https://ads.example/pixel.html?[uid]"]
    assert "SECRET" not in str(env)
    assert "https://ads.example/pixel.html?uid=SECRET" not in t.documents_sent
    assert _summary(wmj_home, clock, env["run_id"])["documents"] == env["data"]["documents"]

def test_main_document_redirect_with_extra_query_is_accepted(cli, probe):
    t = probe([("redirect", SEARCH + "&ka=search_list_1"), ("joblist", load_fixture("api/page1_ok.json"))])
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 0, env
    assert env["data"]["probe"]["login"] == "available" and env["data"]["refused_subframes"] == 0
    assert t.documents_sent[-1] == SEARCH + "&ka=search_list_1"

def test_renamed_list_page_landing_is_accepted(cli, probe):
    """真实核验第五次的场景：落点变成 /web/geek/jobs，同一页改了名，探测不应因此失败。"""
    renamed = SEARCH.replace("/web/geek/job?", "/web/geek/jobs?")
    t = probe([("redirect", renamed), ("joblist", load_fixture("api/page1_ok.json"))])
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 0, env
    assert env["data"]["probe"]["login"] == "available" and env["data"]["documents"] == []
    assert t.documents_sent[-1] == renamed

HANDSHAKE = ("https://www.zhipin.com/web/passport/zp/security.html?appName=zhipin&callbackUrl=%2Fweb%2Fgeek%2Fjob"
             "&code=SYNCODE&name=zp&seed=SYNSEED&ts=1789516920")

def test_platform_handshake_hop_then_back_to_search_succeeds(cli, probe):
    """2026-09-16 实测链路：平台在一次导航里插一跳再跳回搜索页。"""
    t = probe([("redirect", HANDSHAKE), ("redirect", SEARCH), ("joblist", load_fixture("api/page1_ok.json"))])
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 0, env
    assert env["data"]["probe"]["login"] == "available" and env["data"]["documents"] == []
    assert t.documents_sent == [SEARCH, HANDSHAKE, SEARCH]

def test_stuck_on_the_handshake_page_exits_3_with_cooldown(cli, wmj_home, clock, probe):
    from where_my_job.policy.ledger import Ledger
    probe([("redirect", HANDSHAKE), ("joblist", load_fixture("api/page1_ok.json"))])
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 3 and env["errors"][0]["code"] == "RISK_DETECTED"
    c = db.open_db(wmj_home.db_path, clock=clock)
    try:
        assert Ledger(c, clock, wmj_home).cooldown_until() is not None
    finally:
        c.close()

def test_landing_on_another_site_page_fails_without_cooldown(cli, wmj_home, clock, probe):
    from where_my_job.policy.ledger import Ledger
    probe([("redirect", "https://www.zhipin.com/web/geek/recommend?ka=x"), ("joblist", load_fixture("api/page1_ok.json"))])
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 2 and env["errors"][0]["code"] == "CAPTURE_FAILED"
    c = db.open_db(wmj_home.db_path, clock=clock)
    try:
        assert Ledger(c, clock, wmj_home).cooldown_until() is None
    finally:
        c.close()

def test_login_view_landing_reports_unauthenticated_with_landing_note(cli, wmj_home, clock, probe):
    """登录态失效：错误码必须是 UNAUTHENTICATED，且 data.documents 指出停在哪，不进冷却。"""
    from where_my_job.policy.ledger import Ledger
    probe([("same_doc", "https://www.zhipin.com/web/user/?ka=header-login"), ("timeout",)])
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 2 and env["errors"][0]["code"] == "UNAUTHENTICATED"
    assert env["data"]["documents"] == ["landing:https://www.zhipin.com/web/user/?[ka]"]
    assert env["data"]["reason"] == "login_page" and env["data"]["ignored_responses"] == 0
    assert env["data"]["ignored_reasons"] == {}          # 接口根本没发出，与"发了但不匹配"不是一回事
    c = db.open_db(wmj_home.db_path, clock=clock)
    try:
        assert Ledger(c, clock, wmj_home).cooldown_until() is None
    finally:
        c.close()

def test_ignored_responses_are_reported_on_capture_failure(cli, probe):
    """响应到了但不属于本次动作：失败时要说清丢弃了几条，否则离线分不清"接口没发出"与"发了但不匹配"。"""
    probe([("joblist", load_fixture("api/page1_ok.json"), {"query": {"page": "999"}}), ("timeout",)])
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 2 and env["errors"][0]["code"] == "CAPTURE_FAILED"
    assert env["data"]["reason"] == "capture_timeout" and env["data"]["ignored_responses"] == 1
    assert env["data"]["ignored_reasons"] == {"other_parameters": 1}
    assert env["data"]["documents"][:3] == [
        "capture:other_parameters:https://www.zhipin.com/wapi/zpgeek/search/joblist.json?[city,page,query]",
        "params:page=differs", "body:success,items=2,code=0,has_more=true"]

def test_post_login_handshake_round_trip_is_followed(cli, probe):
    """第八次真实核验的场景：刚登录后平台在导航提交之后发起令牌握手往返，探测应当跟随并成功。"""
    hop = ("https://www.zhipin.com/web/passport/zp/security.html?appName=zhipin&callbackUrl=%2Fweb%2Fgeek%2Fjob"
           "&code=SYNCODE&name=zp&seed=SYNSEED&ts=1789516920")
    probe([("hop", hop), ("hop", SEARCH), ("joblist", load_fixture("api/page1_ok.json"))])
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 0, env
    assert env["data"]["probe"]["login"] == "available" and env["data"]["refused_subframes"] == 0
    assert env["data"]["documents"] == [
        "saw:https://www.zhipin.com/web/passport/zp/security.html?[appName,callbackUrl,code,name,seed,ts]"]

def test_probe_accepts_the_list_response_without_search_parameters(cli, probe):
    """第十一次真实核验的场景：平台把搜索条件移出接口地址，探测应当认领这条响应并成功。"""
    bare = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?_=1789554458415"
    probe([("joblist", load_fixture("api/page1_ok.json"), {"url": bare})])
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 0, env
    assert env["data"]["probe"] == {"kind": "success", "login": "available", "has_more": True, "item_count": 2}
    assert env["data"]["documents"] == ["bound:document_only"]
