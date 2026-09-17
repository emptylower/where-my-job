# tests/unit/store/test_migration_0003.py
import json
from datetime import timedelta
from importlib import resources
from where_my_job.config.columns import V_JOBS_COLUMNS
from where_my_job.clock import iso_utc
from where_my_job.store import db, runs, jobs, sightings
from where_my_job.normalize.legacy import map_legacy_record
from tests.conftest import load_fixture

APPLICATION_COLUMNS = {"application_id", "application_state", "followup_due"}

def _cols(conn, view):
    return [r[1] for r in conn.execute(f"pragma table_info({view})")]

def test_builtin_stream_registered_active(conn):
    r = conn.execute("select stream_revision, is_active, definition_json from stream_registry where stream='applications'").fetchone()
    assert r[0] == 1 and r[1] == 1
    assert set(json.loads(r[2])["types"]) == {"applied", "replied", "interview", "offer", "rejected", "withdrawn"}

def test_views_exist(conn):
    names = {r[0] for r in conn.execute("select name from sqlite_master where type='view'")}
    assert {"v_effective_events", "v_job_application", "v_jobs", "v_events"} <= names

def test_v_jobs_columns_exactly_match_contract_in_order(conn):
    cols = _cols(conn, "v_jobs")
    assert len(cols) == 41
    assert cols == ["view_schema_version"] + list(V_JOBS_COLUMNS)

def test_no_read_side_depth_limit_in_effective_view():
    sql = resources.files("where_my_job.store.migrations").joinpath("0003_streams.sql").read_text(encoding="utf-8")
    assert "depth <" not in sql and "c.depth + 1" in sql
    assert sql.count("CREATE VIEW v_jobs AS") == 1 and sql.count("DROP VIEW v_jobs;") == 1

def _ins_event(conn, now, *row):
    conn.execute("""insert into events(event_id,stream,stream_revision,type,subject_kind,subject_id,occurred_at,recorded_at,
                    payload_json,idempotency_key,corrected_event_id,origin) values (?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (row[0], row[1], row[2], row[3], row[4], row[5], row[6], now, row[7], row[8], row[9], row[10]))

def test_effective_events_resolves_chain_and_uses_replacement_time(conn, clock):
    now = iso_utc(clock.now())
    conn.execute("insert into jobs(job_id,source,source_job_id,created_at,updated_at) values ('boss:SYN1','boss','SYN1',?,?)", (now, now))
    conn.execute("insert into applications(application_id, job_id, created_at) values ('app_1','boss:SYN1',?)", (now,))
    _ins_event(conn, now, "evt_a", "applications", 1, "applied", "application", "app_1", "2026-09-10T08:00:00.000000Z", '{"job_id":"boss:SYN1"}', "syn-key-0001", None, "user")
    _ins_event(conn, now, "evt_b", "applications", 1, "replied", "application", "app_1", "2026-09-11T08:00:00.000000Z", '{}', "syn-key-0002", None, "user")
    # replace applied：纠错记录保存自己的 occurred_at（2026-09-14），有效事实使用 replacement_occurred_at
    _ins_event(conn, now, "evt_c", "applications", 1, "corrected", "application", "app_1", "2026-09-14T08:00:00.000000Z",
               '{"op":"replace","original_type":"applied","replacement_payload":{"job_id":"boss:SYN1","channel":"boss"},"replacement_occurred_at":"2026-09-10T09:00:00.000000Z"}',
               "syn-key-0003", "evt_a", "user")
    _ins_event(conn, now, "evt_d", "applications", 1, "corrected", "application", "app_1", "2026-09-14T08:05:00.000000Z", '{"op":"retract"}', "syn-key-0004", "evt_b", "user")
    rows = {r["root_id"]: dict(r) for r in conn.execute("select * from v_effective_events")}
    assert set(rows) == {"evt_a"}
    a = rows["evt_a"]
    assert a["current_id"] == "evt_c" and a["type"] == "applied" and a["occurred_at"] == "2026-09-10T09:00:00.000000Z"
    assert json.loads(a["payload_json"]) == {"job_id": "boss:SYN1", "channel": "boss"} and a["corrected"] == 1
    ja = conn.execute("select * from v_job_application where job_id='boss:SYN1'").fetchone()
    assert ja["application_id"] == "app_1" and ja["application_state"] == "applied" and ja["followup_due"] == 1
    vj = conn.execute("select application_id, application_state, followup_due from v_jobs where job_id='boss:SYN1'").fetchone()
    assert tuple(vj) == ("app_1", "applied", 1)

def test_followup_due_zero_when_replied_or_recent(conn, clock):
    now = iso_utc(clock.now())
    conn.execute("insert into jobs(job_id,source,source_job_id,created_at,updated_at) values ('boss:SYN2','boss','SYN2',?,?)", (now, now))
    conn.execute("insert into applications(application_id, job_id, created_at) values ('app_2','boss:SYN2',?)", (now,))
    _ins_event(conn, now, "evt_e", "applications", 1, "applied", "application", "app_2", "2026-09-14T00:00:00.000000Z", '{"job_id":"boss:SYN2"}', "syn-key-0005", None, "user")
    assert tuple(conn.execute("select followup_due, application_state from v_job_application where job_id='boss:SYN2'").fetchone()) == (0, "applied")
    _ins_event(conn, now, "evt_f", "applications", 1, "replied", "application", "app_2", "2026-09-14T01:00:00.000000Z", '{}', "syn-key-0006", None, "user")
    assert tuple(conn.execute("select followup_due, application_state from v_job_application where job_id='boss:SYN2'").fetchone()) == (0, "replied")

def test_builtin_hash_matches_migration(conn):
    from where_my_job.streams.builtin import APPLICATIONS_DEFINITION, definition_hash
    r = conn.execute("select definition_json, content_hash from stream_registry where stream='applications' and stream_revision=1").fetchone()
    assert json.loads(r[0]) == APPLICATIONS_DEFINITION
    assert r[1] == definition_hash(APPLICATIONS_DEFINITION)

def _apply(conn, versions):
    for version, _name, sql in db._migration_files():
        if version in versions:
            for stmt in db._split_statements(sql):
                conn.execute(stmt)

def _snapshot(conn):
    return {r["job_id"]: dict(r) for r in conn.execute("select * from v_jobs order by job_id")}

def test_0003_changes_only_application_columns(tmp_path, clock):
    """迁移前后逐值对照：除 application 三列外，41 列的名字、顺序和值都不变。"""
    conn = db.open_db(tmp_path / "m.sqlite3", clock=clock)
    db.bind_profile_revision(conn, "syn-profile-0001")
    _apply(conn, {1, 2})
    m1 = map_legacy_record(load_fixture("legacy/合肥_AI产品经理.json")["jobs"][0])
    m2 = map_legacy_record(load_fixture("legacy/合肥_AI产品经理.json")["jobs"][1])
    with db.write_tx(conn):
        rid = runs.create(conn, clock, kind="import", config={"files": ["syn"]}, planned=1)
        tid = runs.add_task(conn, clock, rid, task_key="000000:syn.json", query={})
        for i, m in enumerate((m1, m2)):
            jobs.ensure(conn, clock, m.job_id, "boss", m.source_job_id, m.legacy_job_id, None)
            sightings.insert(conn, clock, job_id=m.job_id, run_id=rid, task_id=tid, file_sha256="d" * 64, item_index=i,
                             page=None, observed_at=clock.now() - timedelta(days=5), observed_at_raw=None,
                             time_precision="file_snapshot", tz_assumption=None, raw_kind="legacy_mapped",
                             raw=m.raw_private, fact=m.fact)
            jobs.refresh_current(conn, clock, m.job_id)
        runs.finish(conn, clock, rid, status="ok", completed=1, summary={})
        mid = runs.create(conn, clock, kind="match", config={"tiers": {"S": 90, "A": 75, "B": 60, "C": 40}, "fallback_tier": "D",
                                                              "profile_revision": "syn-profile-0001"}, planned=2)
        runs.finish(conn, clock, mid, status="ok", completed=2, summary={})
        cur = {r[0]: r[1] for r in conn.execute("select j.job_id, s.content_hash from jobs j join sightings s on s.observation_id=j.current_sighting_id")}
        for m, score in ((m1, 70.0), (m2, None)):
            conn.execute("""insert into match_results(match_run_id, job_id, fact_revision, scoring_hash, profile_revision, engine_version,
                            as_of, dir, excluded, rule_score, tier, reasons_json, exclusion_reasons_json, unknowns_json)
                            values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (mid, m.job_id, cur[m.job_id], "h" * 64, "syn-profile-0001", "engine-1", iso_utc(clock.now()),
                          "AI产品经理" if score is not None else None, 0 if score is not None else 1, score,
                          "B" if score is not None else None,
                          json.dumps([{"rule_id": "base", "delta": 70, "reason": "合成"}] if score is not None else []),
                          json.dumps([] if score is not None else [{"rule_id": "degree-limit", "reason": "合成"}]), "[]"))
        now = iso_utc(clock.now())
        conn.execute("insert into job_attrs(job_id,key,value_json,source,updated_at) values (?,?,?,?,?)",
                     (m1.job_id, "score_adjustment", json.dumps({"delta": 10, "reason": "合成调整", "match_run_id": mid}, ensure_ascii=False), "user", now))
        conn.execute("insert into job_attrs(job_id,key,value_json,source,updated_at) values (?,?,?,?,?)", (m1.job_id, "priority", '"focus"', "user", now))
        conn.execute("insert into job_attrs(job_id,key,value_json,source,updated_at) values (?,?,?,?,?)", (m2.job_id, "priority", '"later"', "agent", now))
    before_cols = _cols(conn, "v_jobs")
    before = _snapshot(conn)
    _apply(conn, {3})
    assert _cols(conn, "v_jobs") == before_cols == ["view_schema_version"] + list(V_JOBS_COLUMNS)
    now = iso_utc(clock.now())
    conn.execute("insert into applications(application_id, job_id, created_at) values ('app_syn_0001', ?, ?)", (m1.job_id, now))
    _ins_event(conn, now, "evt_syn_0001", "applications", 1, "applied", "application", "app_syn_0001", "2026-09-10T08:00:00.000000Z",
               json.dumps({"job_id": m1.job_id}), "syn-key-0100", None, "user")
    after = _snapshot(conn)
    assert set(before) == set(after)
    for job_id, row in before.items():
        for col in before_cols:
            if col in APPLICATION_COLUMNS:
                continue
            assert after[job_id][col] == row[col], (job_id, col)
    assert before[m1.job_id]["score_adjustment"] != 0 and before[m1.job_id]["priority"] == "focus"
    assert (after[m1.job_id]["application_id"], after[m1.job_id]["application_state"], after[m1.job_id]["followup_due"]) == ("app_syn_0001", "applied", 1)
    assert (after[m2.job_id]["application_id"], after[m2.job_id]["application_state"], after[m2.job_id]["followup_due"]) == (None, None, 0)
    conn.close()
