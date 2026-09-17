# tests/integration/test_acquire.py
import json
import pytest
from tests.conftest import FIXTURES, load_fixture
from tests.helpers.fake_transport import FakeTransport
from tests.helpers.sleeper import Sleeper
from where_my_job.errors import Blocked, EnvError, InvalidInput, Partial
from where_my_job.launcher.chrome import BrowserState, VerifiedBrowser
from where_my_job.policy.ledger import Ledger
from where_my_job.policy.lock import is_locked
from where_my_job.service import deepdive as deepdive_svc, deepdive_online
from where_my_job.store import db

pytestmark = pytest.mark.usefixtures("online_adapter_enabled")

VB = VerifiedBrowser(BrowserState(pid=4242, create_time=1000.0, exe="/x", profile="/p", port=9222, started_at="t"),
                     "ws://127.0.0.1:9222/devtools/browser/abc")
JOB = "https://www.zhipin.com/job_detail/SYN0001aaaa.html"
COMPANY = "https://www.zhipin.com/gongsi/SYNCO1.html"

class OkLauncher:
    def verify(self):
        return VB
    def blank_check(self, verified, allow_target_id=None):
        return None

@pytest.fixture
def online(cli, ctx, monkeypatch):
    cli(["import", str(FIXTURES / "legacy" / "合肥_AI产品经理.json")])   # SYN0001aaaa（公司 SYNCO1）、SYN0003cccc（无公司）
    box = {"made": 0}
    def install(script, **kw):
        t = FakeTransport(script, **kw)
        def make(c, verified):
            box["made"] += 1
            return t
        monkeypatch.setattr(deepdive_online, "make_launcher", lambda lay: OkLauncher())
        monkeypatch.setattr(deepdive_online, "make_transport", make)
        monkeypatch.setattr(deepdive_online, "make_pacing", lambda c: (Sleeper(ctx.clock), lambda lo, hi: lo))
        box["t"] = t
        return t
    return install, box

def _evidence(ctx):
    return [dict(r) for r in ctx.conn.execute(
        "select kind, origin, completeness, excerpt, structured_json, full_text from evidence order by rowid")]

def test_two_pages_complete_through_04_lazy_entry(ctx, online):
    install, _ = online
    t = install([("page", load_fixture("pages/job_detail_ok.json")), ("page", load_fixture("pages/company_ok.json"))])
    r = deepdive_svc.acquire(ctx, "boss:SYN0001aaaa", skip_company=False)
    assert r.acquisition_state == "complete" and r.blocked is None and r.failure is None
    assert r.detail_evidence_id and r.company_evidence_id and t.navigations == [JOB, COMPANY] and t.closed
    ev = _evidence(ctx)
    assert [(e["kind"], e["origin"], e["completeness"]) for e in ev] == [("job_detail_page", "cli", "complete"), ("company_page", "cli", "complete")]
    assert all(isinstance(e["excerpt"], str) for e in ev)
    assert json.loads(ev[0]["structured_json"])["ld_json_upDate"] == "2026-09-01"
    assert json.loads(ev[1]["structured_json"])["job_count"] == 22
    assert [e["kind"] for e in Ledger(ctx.conn, ctx.clock, ctx.home).view().entries] == ["detail_page", "company_page"]
    assert ctx.conn.execute("select status from runs where run_id=?", (r.run_id,)).fetchone()[0] == "running"
    assert is_locked(ctx.home) is False

def test_skip_company_is_partial_exit_0(ctx, online):
    install, _ = online
    t = install([("page", load_fixture("pages/job_detail_ok.json"))])
    r = deepdive_online.acquire(ctx, "boss:SYN0001aaaa", skip_company=True)
    assert r.acquisition_state == "partial" and r.failure is None and "company_page:skipped" in r.unknowns
    assert len(t.navigations) == 1

def test_job_without_company_is_partial(ctx, online):
    install, _ = online
    install([("page", load_fixture("pages/job_detail_ok.json"))])
    r = deepdive_online.acquire(ctx, "boss:SYN0003cccc", skip_company=False)
    assert r.acquisition_state == "partial" and "company_page:no_company_id" in r.unknowns and r.failure is None

def test_company_risk_page_keeps_detail_sets_blocked_and_stores_no_risk_text(ctx, online):
    install, _ = online
    install([("page", load_fixture("pages/job_detail_ok.json")), ("page", load_fixture("pages/job_detail_risk.json"))])
    r = deepdive_online.acquire(ctx, "boss:SYN0001aaaa", skip_company=False)
    assert isinstance(r.blocked, Blocked) and r.blocked.code == "RISK_DETECTED" and r.blocked.run_id == r.run_id
    assert r.detail_evidence_id and r.company_evidence_id is None and r.acquisition_state == "partial"
    assert Ledger(ctx.conn, ctx.clock, ctx.home).cooldown_until() is not None
    assert "LEAK-SENTINEL" not in json.dumps(_evidence(ctx), ensure_ascii=False)

def test_detail_login_wall_is_failure_not_exception(ctx, online):
    install, _ = online
    install([("page", load_fixture("pages/job_detail_login_wall.json"))])
    r = deepdive_online.acquire(ctx, "boss:SYN0001aaaa", skip_company=True)
    assert isinstance(r.failure, EnvError) and r.failure.code == "UNAUTHENTICATED" and r.failure.exit_code == 2
    assert r.detail_evidence_id is None and _evidence(ctx) == []

def test_company_redirect_after_detail_is_partial_failure(ctx, online):
    install, _ = online
    install([("page", load_fixture("pages/job_detail_ok.json")), ("redirect", "https://evil.example/x")])
    r = deepdive_online.acquire(ctx, "boss:SYN0001aaaa", skip_company=False)
    assert isinstance(r.failure, Partial) and r.failure.code == "PARTIAL_RESULT" and r.detail_evidence_id

def test_truncated_and_garbage_details_are_partial(ctx, online):
    install, _ = online
    install([("page", load_fixture("pages/job_detail_truncated.json"))])
    r = deepdive_online.acquire(ctx, "boss:SYN0001aaaa", skip_company=True)
    assert _evidence(ctx)[-1]["completeness"] == "partial" and "job_detail:text_truncated" in r.unknowns
    install([("page", load_fixture("pages/job_detail_garbage.json"))])
    ctx.clock.advance(60)
    r2 = deepdive_online.acquire(ctx, "boss:SYN0001aaaa", skip_company=True)
    assert _evidence(ctx)[-1]["completeness"] == "unparsed" and "job_detail:jd" in r2.unknowns

def test_cooldown_refused_before_run_and_transport(ctx, online):
    install, box = online
    install([("page", load_fixture("pages/job_detail_ok.json"))])
    with db.write_tx(ctx.conn):
        Ledger(ctx.conn, ctx.clock, ctx.home).set_cooldown("risk_response", platform_code=31)
    with pytest.raises(Blocked) as ei:
        deepdive_online.acquire(ctx, "boss:SYN0001aaaa", skip_company=True)
    assert ei.value.code == "COOLDOWN_ACTIVE" and ei.value.run_id is None and box["made"] == 0
    assert ctx.conn.execute("select count(*) from runs where kind='deepdive'").fetchone()[0] == 0

def test_unknown_job_not_found_before_run(ctx, online):
    install, _ = online
    install([])
    with pytest.raises(InvalidInput) as ei:
        deepdive_online.acquire(ctx, "boss:NOPE", skip_company=True)
    assert ei.value.code == "NOT_FOUND"

def test_internal_error_after_run_is_captured_not_raised(ctx, online, monkeypatch):
    install, _ = online
    install([("page", load_fixture("pages/job_detail_ok.json"))])
    monkeypatch.setattr(deepdive_online, "parse_job_detail", lambda extracted: (_ for _ in ()).throw(ValueError("LEAK-SENTINEL")))
    r = deepdive_online.acquire(ctx, "boss:SYN0001aaaa", skip_company=True)
    assert r.failure.code == "INTERNAL" and "LEAK" not in r.failure.message

def test_cli_deepdive_end_to_end_complete_and_blocked(cli, ctx, online):
    install, _ = online
    install([("page", load_fixture("pages/job_detail_ok.json")), ("page", load_fixture("pages/company_ok.json"))])
    rc, env, _ = cli(["deepdive", "boss:SYN0001aaaa"])
    assert rc == 0 and env["run_id"] and "bundle_id" in json.dumps(env["data"])
    ctx.clock.advance(3600)
    install([("page", load_fixture("pages/job_detail_risk.json"))])
    rc, env, _ = cli(["deepdive", "boss:SYN0001aaaa", "--skip-company"])
    assert rc == 3 and env["errors"][0]["code"] == "RISK_DETECTED" and env["run_id"]
    assert "LEAK-SENTINEL" not in json.dumps(env, ensure_ascii=False)
