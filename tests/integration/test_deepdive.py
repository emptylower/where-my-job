# tests/integration/test_deepdive.py
import json
import pytest
from tests.helpers.evidence_seed import seed_job, seed_detail, seed_company_page
from where_my_job.errors import Blocked, EnvError
from where_my_job.service import deepdive
from where_my_job.store import db, evidence, runs

pytestmark = pytest.mark.usefixtures("online_adapter_enabled")

JOB = "boss:SYN0001aaaa"

def _keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _keys(v)

def _fake(outcome: str):
    """模拟 05 的 acquire：create_owned 之后不抛异常，把风控放 blocked、其它失败放 failure。"""
    def fake(ctx, job_id, *, skip_company):
        run_id = runs.create_owned(ctx, kind="deepdive", config={"job_id": job_id, "fake": outcome}, planned=2)
        detail = company = None
        if outcome in ("complete", "detail_only", "blocked_after_detail", "failure_after_detail"):
            with db.write_tx(ctx.conn):
                detail = evidence.insert_cli(
                    ctx.conn, ctx.clock, job_id=job_id, company_id=None, kind="job_detail_page",
                    url="https://www.zhipin.com/job_detail/SYN0001aaaa.html", captured_at=ctx.clock.now(),
                    excerpt="职位描述\n合成 JD", full_text="职位描述\n合成 JD 全文", structured={"boss_title": "产品总监"},
                    parser_version="detail-v1", completeness="complete", run_id=run_id,
                    idempotency_key=f"fake-detail-{run_id}")
        if outcome == "complete":
            with db.write_tx(ctx.conn):
                company = evidence.insert_cli(
                    ctx.conn, ctx.clock, job_id=None, company_id="boss:SYNCO1", kind="company_page",
                    url="https://www.zhipin.com/gongsi/SYNCO1.html", captured_at=ctx.clock.now(),
                    excerpt="合成科技一号", full_text=None,
                    structured={"job_count": 12, "boss_count": 3, "job_count_raw": "在招职位 12", "boss_count_raw": "招聘者 3"},
                    parser_version="company-v1", completeness="complete", run_id=run_id,
                    idempotency_key=f"fake-company-{run_id}")
        blocked = Blocked("RISK_DETECTED", "检测到平台访问限制，已停止并进入冷却") if outcome.startswith("blocked") else None
        failure = EnvError("CAPTURE_FAILED", "未取得可验证的页面响应，已停止") if outcome.startswith("failure") else None
        return deepdive.AcquisitionResult(run_id=run_id, detail_evidence_id=detail, company_evidence_id=company,
                                          acquisition_state="complete" if outcome == "complete" else "partial",
                                          unknowns=[] if outcome == "complete" else ["company_page: 未取得"],
                                          blocked=blocked, failure=failure)
    return fake

def _count(conn, table, where="1=1"):
    return conn.execute(f"select count(*) from {table} where {where}").fetchone()[0]

def test_cached_complete_bundle(cli, conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    c = seed_company_page(conn, clock, "boss:SYNCO1")
    rc, env, _ = cli(["deepdive", JOB, "--cached"])
    assert rc == 0, env
    b = env["data"]["bundle"]
    assert b["acquisition_state"] == "complete" and [e["evidence_id"] for e in b["evidence"]] == [d, c]
    assert env["data"]["report_state"] == "analysis_pending" and env["run_id"].startswith("run_")
    assert b["signals"]["company_counts"]["ratio"] == 0.25 and b["signals"]["observation_span"]["days"] == 0
    assert "full_text" not in set(_keys(b)) and "SYNBOSS" not in json.dumps(b, ensure_ascii=False)
    assert tuple(conn.execute("select kind, status from runs where run_id=?", (env["run_id"],)).fetchone()) == ("deepdive", "ok")

def test_cached_partial_labels(cli, conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    seed_detail(conn, clock, JOB)
    rc, env, _ = cli(["deepdive", JOB, "--cached"])
    assert rc == 0 and env["data"]["bundle"]["acquisition_state"] == "partial"
    assert env["data"]["bundle"]["unknowns"] == ["company_page: 无缓存证据"]
    rc, env, _ = cli(["deepdive", JOB, "--cached", "--skip-company"])
    assert rc == 0 and env["data"]["bundle"]["unknowns"] == ["company_page: 按 --skip-company 未采集"]
    assert env["data"]["bundle"]["acquisition_state"] == "partial"

def test_cached_unparsed_or_truncated_detail_is_partial(cli, conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    seed_company_page(conn, clock, "boss:SYNCO1")
    seed_detail(conn, clock, JOB, captured_at="2026-09-13T09:00:00Z", completeness="unparsed")
    rc, env, _ = cli(["deepdive", JOB, "--cached"])
    assert rc == 0 and env["data"]["bundle"]["acquisition_state"] == "partial"
    assert "job_detail_page: completeness=unparsed" in env["data"]["bundle"]["unknowns"]
    seed_detail(conn, clock, JOB, captured_at="2026-09-14T09:30:00Z",
                structured={"boss_title": "产品总监", "text_truncated": True})
    rc, env, _ = cli(["deepdive", JOB, "--cached"])
    assert env["data"]["bundle"]["acquisition_state"] == "partial"
    assert "job_detail_page: 正文截断" in env["data"]["bundle"]["unknowns"]

def test_cached_no_detail_is_not_found_and_creates_no_run(cli, conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    rc, env, _ = cli(["deepdive", JOB, "--cached"])
    assert rc == 1 and env["errors"][0]["code"] == "NOT_FOUND" and "详情页" in env["errors"][0]["message"]
    assert _count(conn, "runs", "kind='deepdive'") == 0

def test_cached_uses_latest_detail(cli, conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    seed_detail(conn, clock, JOB, captured_at="2026-09-10T09:00:00Z")
    new = seed_detail(conn, clock, JOB, captured_at="2026-09-13T09:00:00Z")
    rc, env, _ = cli(["deepdive", JOB, "--cached", "--skip-company"])
    assert rc == 0 and env["data"]["bundle"]["evidence"][0]["evidence_id"] == new

def test_online_complete_via_injected_acquire(cli, conn, clock, monkeypatch):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    monkeypatch.setattr(deepdive, "_acquire", _fake("complete"))
    rc, env, _ = cli(["deepdive", JOB])
    assert rc == 0, env
    assert env["data"]["bundle"]["acquisition_state"] == "complete" and env["data"]["cached"] is False
    assert tuple(conn.execute("select status from runs where run_id=?", (env["run_id"],)).fetchone()) == ("ok",)

def test_online_skip_company_is_partial_exit_0(cli, conn, clock, monkeypatch):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    monkeypatch.setattr(deepdive, "_acquire", _fake("detail_only"))
    rc, env, _ = cli(["deepdive", JOB, "--skip-company"])
    assert rc == 0 and env["data"]["bundle"]["acquisition_state"] == "partial"
    assert "company_page: 按 --skip-company 未采集" in env["data"]["bundle"]["unknowns"]

def test_online_blocked_with_saved_detail_exits_3_and_keeps_bundle(cli, conn, clock, monkeypatch):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    monkeypatch.setattr(deepdive, "_acquire", _fake("blocked_after_detail"))
    rc, env, _ = cli(["deepdive", JOB])
    assert rc == 3 and env["errors"][0]["code"] == "RISK_DETECTED" and env["run_id"] is not None
    assert env["data"]["bundle"]["acquisition_state"] == "partial" and env["data"]["bundle_id"]
    assert tuple(conn.execute("select status from runs where run_id=?", (env["run_id"],)).fetchone()) == ("blocked",)
    assert _count(conn, "evidence_bundles") == 1

def test_online_failure_with_saved_detail_exits_4(cli, conn, clock, monkeypatch):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    monkeypatch.setattr(deepdive, "_acquire", _fake("failure_after_detail"))
    rc, env, _ = cli(["deepdive", JOB])
    assert rc == 4 and env["errors"][0]["code"] == "PARTIAL_RESULT" and env["run_id"] is not None
    assert env["data"]["bundle"]["acquisition_state"] == "partial"
    assert tuple(conn.execute("select status from runs where run_id=?", (env["run_id"],)).fetchone()) == ("partial",)

def test_online_failure_without_evidence_creates_no_bundle(cli, conn, clock, monkeypatch):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    monkeypatch.setattr(deepdive, "_acquire", _fake("failure_no_evidence"))
    rc, env, _ = cli(["deepdive", JOB])
    assert rc == 2 and env["errors"][0]["code"] == "CAPTURE_FAILED" and env["run_id"] is not None
    assert _count(conn, "evidence_bundles") == 0
    assert tuple(conn.execute("select status from runs where run_id=?", (env["run_id"],)).fetchone()) == ("failed",)

def test_online_blocked_without_evidence_exits_3_no_bundle(cli, conn, clock, monkeypatch):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    monkeypatch.setattr(deepdive, "_acquire", _fake("blocked_no_evidence"))
    rc, env, _ = cli(["deepdive", JOB])
    assert rc == 3 and env["errors"][0]["code"] == "RISK_DETECTED"
    assert _count(conn, "evidence_bundles") == 0

def test_unknown_job(cli):
    rc, env, _ = cli(["deepdive", "boss:NOPE", "--cached"])
    assert rc == 1 and env["errors"][0]["code"] == "NOT_FOUND"
