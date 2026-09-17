# tests/unit/store/test_reports_state.py
import json
import pytest
from tests.conftest import load_fixture
from tests.helpers.evidence_seed import seed_job, seed_detail, seed_company_page, seed_web
from where_my_job.store import db, runs, bundles, reports
from where_my_job.errors import InvalidInput

JOB = "boss:SYN0001aaaa"
REV = "example-minimal-v1"

@pytest.fixture(autouse=True)
def _bind_profile(conn):
    db.bind_profile_revision(conn, REV)

def _bundle(conn, clock, ids, state="complete"):
    with db.write_tx(conn):
        run_id = runs.create(conn, clock, kind="deepdive", config={}, planned=1)
        return bundles.create(conn, clock, job_id=JOB, run_id=run_id, evidence_ids=ids, acquisition_state=state, unknowns=[])

def _report(bundle_id, detail_id, name="only_supporting", **over):
    text = json.dumps(load_fixture(f"reports/{name}.json"), ensure_ascii=False)
    r = json.loads(text.replace("__BUNDLE_ID__", bundle_id).replace("__DETAIL_EVIDENCE_ID__", detail_id))
    r.update(over)
    return r

def _state(conn):
    return tuple(conn.execute("select current_bundle_id, report_id, report_state from v_jobs where job_id=?", (JOB,)).fetchone())

def _count(conn, table, where="1=1"):
    return conn.execute(f"select count(*) from {table} where {where}").fetchone()[0]

def test_state_none_then_pending_then_complete(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    assert _state(conn) == (None, None, "none")
    d = seed_detail(conn, clock, JOB)
    c = seed_company_page(conn, clock, "boss:SYNCO1")
    b = _bundle(conn, clock, [d, c])
    assert _state(conn) == (b, None, "analysis_pending")
    with db.write_tx(conn):
        rid, created = reports.insert(conn, clock, _report(b, d))
    assert created is True and rid.startswith("rpt_")
    assert _state(conn) == (b, rid, "complete")
    attrs = {r["key"]: json.loads(r["value_json"]) for r in
             conn.execute("select key, value_json from job_attrs where job_id=? and source='agent'", (JOB,))}
    assert attrs["authentic"]["conclusion"] == "倾向真实在招" and attrs["authentic"]["report_id"] == rid
    assert attrs["jd_translation"]["sentences"][0]["original"] == "负责 AI 产品从 0 到 1"

def test_idempotent_and_conflict(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    b = _bundle(conn, clock, [d], "partial")
    with db.write_tx(conn):
        rid, _ = reports.insert(conn, clock, _report(b, d))
        rid2, created = reports.insert(conn, clock, _report(b, d))
    assert rid == rid2 and created is False
    changed = _report(b, d)
    changed["report_md"] += "\n补一句"
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            reports.insert(conn, clock, changed)
    assert ei.value.code == "IDEMPOTENCY_CONFLICT"
    assert _count(conn, "deepdives") == 1

def test_new_bundle_or_new_fact_makes_report_stale(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    b = _bundle(conn, clock, [d])
    with db.write_tx(conn):
        rid, _ = reports.insert(conn, clock, _report(b, d))
    clock.advance(1)
    b2 = _bundle(conn, clock, [d])
    assert _state(conn) == (b2, rid, "stale")
    with db.write_tx(conn):
        reports.insert(conn, clock, _report(b2, d, idempotency_key="syn-rpt-rebound-1"))
    assert _state(conn)[2] == "complete"
    clock.advance(3600)
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1", fixture_index=1)
    assert _state(conn)[2] == "stale"

def test_profile_revision_change_or_absence_makes_stale(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    b = _bundle(conn, clock, [d])
    with db.write_tx(conn):
        reports.insert(conn, clock, _report(b, d))
    assert _state(conn)[2] == "complete"
    db.bind_profile_revision(conn, "example-minimal-v2")
    assert _state(conn)[2] == "stale"
    db.bind_profile_revision(conn, None)
    assert _state(conn)[2] == "stale"
    db.bind_profile_revision(conn, REV)
    assert _state(conn)[2] == "complete"

def test_reference_only_in_extra_allowed_and_outside_closure_rejected(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    b = _bundle(conn, clock, [d])
    w1 = seed_web(conn, clock, JOB, "syn-ev-extra-0001")
    r = _report(b, d, extra_evidence_ids=[w1])
    r["authentic"]["supporting"][0]["evidence_id"] = w1
    with db.write_tx(conn):
        rid, _ = reports.insert(conn, clock, r)
    got = reports.get(conn, JOB, report_id=rid)
    assert got["bundle_id"] != b and w1 in [e["evidence_id"] for e in got["bundle"]["evidence"]]
    assert _state(conn) == (got["bundle_id"], rid, "complete")
    w2 = seed_web(conn, clock, JOB, "syn-ev-extra-0002", url="https://example.com/other")
    r2 = _report(got["bundle_id"], d, idempotency_key="syn-rpt-closure-2")
    r2["authentic"]["supporting"][0]["evidence_id"] = w2
    before = (_count(conn, "evidence_bundles"), _count(conn, "deepdives"))
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            reports.insert(conn, clock, r2)
    assert ei.value.code == "EVIDENCE_REF_INVALID" and ei.value.path == "$.authentic.supporting[0].evidence_id"
    assert (_count(conn, "evidence_bundles"), _count(conn, "deepdives")) == before

def test_racing_new_bundle_rejects_old_input_without_side_effects(conn, clock, wmj_home):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    b1 = _bundle(conn, clock, [d])
    obj = _report(b1, d)
    other = db.open_db(wmj_home.db_path, clock=clock)
    try:
        clock.advance(1)
        with db.write_tx(other):
            run_id = runs.create(other, clock, kind="deepdive", config={}, planned=1)
            bundles.create(other, clock, job_id=JOB, run_id=run_id, evidence_ids=[d], acquisition_state="complete", unknowns=[])
    finally:
        other.close()
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            reports.insert(conn, clock, obj)
    assert ei.value.code == "BUNDLE_STALE"
    assert _count(conn, "evidence_bundles") == 2 and _count(conn, "deepdives") == 0
    assert _count(conn, "job_attrs", "key in ('authentic','jd_translation')") == 0

def test_retry_after_new_bundle_returns_original_report(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    b1 = _bundle(conn, clock, [d])
    obj = _report(b1, d)
    with db.write_tx(conn):
        rid, _ = reports.insert(conn, clock, obj)
    clock.advance(1)
    _bundle(conn, clock, [d])
    with db.write_tx(conn):
        again, created = reports.insert(conn, clock, obj)
    assert again == rid and created is False and _count(conn, "deepdives") == 1

def test_get_report_includes_frozen_bundle_and_stale_flag(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    b = _bundle(conn, clock, [d], "partial")
    with db.write_tx(conn):
        rid, _ = reports.insert(conn, clock, _report(b, d, "partial"))
    r = reports.get(conn, JOB, report_id=None)
    assert r["report_id"] == rid and r["bundle"]["acquisition_state"] == "partial" and r["report_state"] == "complete"
    assert r["structured"]["authentic"]["conclusion"] == "证据不足" and r["report_md"].startswith("## 招聘信号判断")
    assert "_content_hash" not in r["structured"]
    assert reports.persisted_summary(conn, rid) == {"report_id": rid, "bundle_id": b, "bundle_version": 1,
                                                    "report_state": "complete"}
    assert reports.get(conn, JOB, report_id="rpt_nope") is None
