# tests/unit/store/test_matches_attrs.py
import json
import pytest
from where_my_job.store import db, runs, jobs, sightings, matches, attrs
from where_my_job.normalize.legacy import map_legacy_record
from where_my_job.errors import InvalidInput
from tests.conftest import load_fixture

V_JOBS_COLUMN_ORDER = [
    "view_schema_version", "job_id", "legacy_job_id", "title", "job_url", "company_id", "company_name", "city", "district",
    "salary_text", "salary_lo", "salary_hi", "salary_currency", "salary_period", "pay_months", "exp", "degree", "skills_json",
    "fact_revision", "first_seen_at", "last_seen_at", "seen_run_count", "hit_count", "match_run_id", "dir", "match_state",
    "rule_score", "score_adjustment", "score", "tier", "reasons_json", "excluded", "exclusion_reasons_json", "unknowns_json",
    "priority", "current_bundle_id", "report_id", "report_state", "application_id", "application_state", "followup_due",
]

def _seed(conn, clock, idx=0):
    m = map_legacy_record(load_fixture("legacy/合肥_AI产品经理.json")["jobs"][idx])
    with db.write_tx(conn):
        run_id = runs.create(conn, clock, kind="import", config={}, planned=1)
        task_id = runs.add_task(conn, clock, run_id, task_key="f", query={})
        jobs.ensure(conn, clock, m.job_id, "boss", m.source_job_id, m.legacy_job_id, None)
        sightings.insert(conn, clock, job_id=m.job_id, run_id=run_id, task_id=task_id, file_sha256="a"*64, item_index=idx,
                         page=None, observed_at=clock.now(), observed_at_raw=None, time_precision="file_snapshot",
                         tz_assumption=None, raw_kind="legacy_mapped", raw={}, fact=m.fact)
        jobs.refresh_current(conn, clock, m.job_id)
    return m

def _match_row(job_id, fact_rev, score=70.0, tier="B"):
    return dict(job_id=job_id, fact_revision=fact_rev, dir="AI产品经理", excluded=0, rule_score=score, tier=tier,
                reasons=[{"rule_id": "base", "delta": score, "reason": "x"}], exclusion_reasons=[], unknowns=[])

def _one_run(conn, clock, job_id, rev, *, profile="p1", score=70.0, tier="B"):
    with db.write_tx(conn):
        run_id = matches.begin_run(conn, clock, scoring_hash="h1", profile_revision=profile, tiers={"S": 90, "A": 75, "B": 60, "C": 40},
                                   fallback_tier="D", as_of="2026-09-14T12:00:00.000000Z", campus={"value": "include", "basis": "no_experience_filter"}, planned=1)
        matches.insert_results(conn, run_id, [_match_row(job_id, rev, score, tier)], scoring_hash="h1", profile_revision=profile,
                               engine_version="rules-1", as_of="2026-09-14T12:00:00.000000Z")
        matches.commit_run(conn, clock, run_id, completed=1, summary={})
    return run_id

def test_v_jobs_column_order_is_contract(conn):
    cols = [d[0] for d in conn.execute("select * from v_jobs limit 0").description]
    assert cols == V_JOBS_COLUMN_ORDER and len(cols) == 41

def test_v_jobs_match_columns_current_and_stale(conn, clock):
    m = _seed(conn, clock)
    db.bind_profile_revision(conn, "p1")
    rev = conn.execute("select fact_revision from v_jobs where job_id=?", (m.job_id,)).fetchone()[0]
    run_id = _one_run(conn, clock, m.job_id, rev)
    r = conn.execute("select * from v_jobs where job_id=?", (m.job_id,)).fetchone()
    assert r["match_run_id"] == run_id and r["match_state"] == "current" and r["rule_score"] == 70.0
    assert r["score"] == 70.0 and r["tier"] == "B" and r["excluded"] == 0 and json.loads(r["reasons_json"])[0]["rule_id"] == "base"
    # 画像版本变化或未绑定 → stale
    db.bind_profile_revision(conn, "p2")
    assert conn.execute("select match_state from v_jobs where job_id=?", (m.job_id,)).fetchone()[0] == "stale"
    db.bind_profile_revision(conn, None)
    assert conn.execute("select match_state from v_jobs where job_id=?", (m.job_id,)).fetchone()[0] == "stale"
    db.bind_profile_revision(conn, "p1")
    # 事实更新 → stale
    with db.write_tx(conn):
        run2 = runs.create(conn, clock, kind="import", config={}, planned=1)
        t2 = runs.add_task(conn, clock, run2, task_key="g", query={})
        m2 = map_legacy_record({**load_fixture("legacy/合肥_AI产品经理.json")["jobs"][0], "title": "AI产品经理（新）"})
        clock.advance(60)
        sightings.insert(conn, clock, job_id=m.job_id, run_id=run2, task_id=t2, file_sha256="b"*64, item_index=0, page=None,
                         observed_at=clock.now(), observed_at_raw=None, time_precision="file_snapshot", tz_assumption=None,
                         raw_kind="legacy_mapped", raw={}, fact=m2.fact)
        jobs.refresh_current(conn, clock, m.job_id)
    r = conn.execute("select match_state, title from v_jobs where job_id=?", (m.job_id,)).fetchone()
    assert r["match_state"] == "stale" and r["title"] == "AI产品经理（新）"

def test_latest_run_wins_under_fixed_clock(conn, clock):
    m = _seed(conn, clock)
    db.bind_profile_revision(conn, "p1")
    rev = conn.execute("select fact_revision from v_jobs where job_id=?", (m.job_id,)).fetchone()[0]
    ids = [_one_run(conn, clock, m.job_id, rev, score=60.0 + i) for i in range(5)]    # started_at 全相同
    assert matches.current_run(conn)["run_id"] == ids[-1]
    assert conn.execute("select rule_score from v_jobs where job_id=?", (m.job_id,)).fetchone()[0] == 64.0

def test_failed_run_keeps_previous_batch(conn, clock):
    m = _seed(conn, clock)
    rev = conn.execute("select fact_revision from v_jobs where job_id=?", (m.job_id,)).fetchone()[0]
    r1 = _one_run(conn, clock, m.job_id, rev)
    with pytest.raises(RuntimeError):
        with db.write_tx(conn):
            r2 = matches.begin_run(conn, clock, scoring_hash="h2", profile_revision="p1", tiers={"S": 90}, fallback_tier="D", as_of="t", campus={}, planned=1)
            matches.insert_results(conn, r2, [_match_row(m.job_id, rev, 99)], scoring_hash="h2", profile_revision="p1", engine_version="rules-1", as_of="t")
            raise RuntimeError("boom")
    r = conn.execute("select match_run_id, rule_score from v_jobs where job_id=?", (m.job_id,)).fetchone()
    assert r["match_run_id"] == r1 and r["rule_score"] == 70.0
    assert matches.current_run(conn)["run_id"] == r1

def test_attrs_precedence_adjustment_reason_and_tier_recompute(conn, clock):
    m = _seed(conn, clock)
    rev = conn.execute("select fact_revision from v_jobs where job_id=?", (m.job_id,)).fetchone()[0]
    run_id = _one_run(conn, clock, m.job_id, rev)
    with db.write_tx(conn):
        attrs.set_attr(conn, clock, m.job_id, "priority", "later", source="agent")
        attrs.set_attr(conn, clock, m.job_id, "priority", "focus", source="user")
        attrs.set_attr(conn, clock, m.job_id, "score_adjustment", {"delta": 10, "reason": "作品集对口", "match_run_id": run_id}, source="user")
        attrs.set_attr(conn, clock, m.job_id, "custom.remote_ok", True, source="agent")
    r = conn.execute("select priority, score_adjustment, score, tier, reasons_json from v_jobs where job_id=?", (m.job_id,)).fetchone()
    assert (r["priority"], r["score_adjustment"], r["score"], r["tier"]) == ("focus", 10.0, 80.0, "A")
    reasons = json.loads(r["reasons_json"])
    assert reasons[-1] == {"rule_id": "user-adjustment", "delta": 10, "reason": "作品集对口", "source": "user", "match_run_id": run_id}
    assert sum(x["delta"] for x in reasons) == r["score"]
    with db.write_tx(conn):
        attrs.set_attr(conn, clock, m.job_id, "score_adjustment", {"delta": 0, "reason": "复核后不调整", "match_run_id": run_id}, source="user")
    reasons = json.loads(conn.execute("select reasons_json from v_jobs where job_id=?", (m.job_id,)).fetchone()[0])
    assert reasons[-1]["rule_id"] == "user-adjustment" and reasons[-1]["delta"] == 0       # delta=0 仍保留理由
    with db.write_tx(conn):
        attrs.unset_attr(conn, m.job_id, "priority", source="user")
    assert conn.execute("select priority from v_jobs where job_id=?", (m.job_id,)).fetchone()[0] == "later"
    # 关联过期的调整不生效、不进理由，但仍可查
    with db.write_tx(conn):
        attrs.set_attr(conn, clock, m.job_id, "score_adjustment", {"delta": 10, "reason": "x", "match_run_id": "run_old"}, source="user")
    r = conn.execute("select score_adjustment, score, tier, reasons_json from v_jobs where job_id=?", (m.job_id,)).fetchone()
    assert (r["score_adjustment"], r["score"], r["tier"]) == (0.0, 70.0, "B")
    assert all(x["rule_id"] != "user-adjustment" for x in json.loads(r["reasons_json"]))
    assert {a["key"] for a in attrs.list_attrs(conn, m.job_id)} == {"custom.remote_ok", "priority", "score_adjustment"}

def test_attr_contract_rejections(conn, clock):
    m = _seed(conn, clock)
    with db.write_tx(conn):
        for key, val, src in [("priority", "urgent", "user"), ("authentic", {"x": 1}, "agent"), ("jd_translation", "t", "user"),
                              ("score", 1, "user"), ("Custom.X", 1, "user"), ("custom.ok", "x" * 9000, "user"),
                              ("score_adjustment", {"delta": 500, "reason": "r", "match_run_id": "m"}, "user"),
                              ("score_adjustment", {"delta": 5, "reason": "r", "match_run_id": "m"}, "agent"),
                              ("custom.nan", float("nan"), "user"), ("custom.inf", [1, float("inf")], "user"),
                              ("note", "n" * 5000, "user")]:
            with pytest.raises(InvalidInput):
                attrs.set_attr(conn, clock, m.job_id, key, val, source=src)
        for i in range(64):
            attrs.set_attr(conn, clock, m.job_id, f"custom.k{i}", i, source="agent")
        with pytest.raises(InvalidInput):
            attrs.set_attr(conn, clock, m.job_id, "custom.k64", 1, source="agent")
    assert conn.execute("select count(*) from job_attrs").fetchone()[0] == 64
