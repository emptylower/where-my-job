import json, sqlite3
from datetime import timedelta
import pytest
from where_my_job.clock import iso_utc
from where_my_job.store import db, runs, jobs, companies, sightings
from where_my_job.normalize.legacy import map_legacy_record
from tests.conftest import load_fixture

def _mapped(i):
    return map_legacy_record(load_fixture("legacy/合肥_AI产品经理.json")["jobs"][i])

def _sighting(conn, clock, m, run_id, task_id, *, sha, index=0, observed_at):
    return sightings.insert(conn, clock, job_id=m.job_id, run_id=run_id, task_id=task_id, file_sha256=sha,
                            item_index=index, page=None, observed_at=observed_at, observed_at_raw=None,
                            time_precision="file_snapshot", tz_assumption=None, raw_kind="legacy_mapped",
                            raw=m.raw_private, fact=m.fact)

def test_run_and_task_lifecycle(conn, clock):
    with db.write_tx(conn):
        run_id = runs.create(conn, clock, kind="import", config={"files": ["a.json"]}, planned=1)
        task_id = runs.add_task(conn, clock, run_id, task_key="000000:a.json", query={"source_name": "a.json"})
        runs.finish_task(conn, clock, task_id, status="ok")
        runs.update_progress(conn, run_id, completed=1, summary={"obs": 3})
        runs.finish(conn, clock, run_id, status="ok", completed=1, summary={"obs": 3})
    r = conn.execute("select * from runs where run_id=?", (run_id,)).fetchone()
    assert r["status"] == "ok" and r["completed_count"] == 1 and json.loads(r["summary_json"]) == {"obs": 3}
    assert conn.execute("select status from run_tasks where task_id=?", (task_id,)).fetchone()[0] == "ok"

def test_upsert_company_job_sighting_updates_current(conn, clock):
    m = _mapped(0)
    t1 = clock.now() - timedelta(days=2)
    with db.write_tx(conn):
        run_id = runs.create(conn, clock, kind="import", config={}, planned=1)
        task_id = runs.add_task(conn, clock, run_id, task_key="000000:f", query={})
        companies.ensure(conn, clock, m.company_id, "boss", "SYNCO1", m.company_name)
        jobs.ensure(conn, clock, m.job_id, "boss", m.source_job_id, m.legacy_job_id, m.company_id)
        obs1 = _sighting(conn, clock, m, run_id, task_id, sha="f" * 64, observed_at=t1)
        jobs.refresh_current(conn, clock, m.job_id)
    j = conn.execute("select * from jobs where job_id=?", (m.job_id,)).fetchone()
    assert j["current_sighting_id"] == obs1 and j["hit_count"] == 1 and j["seen_run_count"] == 1
    assert j["first_seen_at"] == j["last_seen_at"] == iso_utc(t1)

def test_older_file_imported_later_does_not_override_newer(conn, clock):
    m = _mapped(0)
    with db.write_tx(conn):
        run_a = runs.create(conn, clock, kind="import", config={}, planned=1)
        task_a = runs.add_task(conn, clock, run_a, task_key="000000:a", query={})
        run_b = runs.create(conn, clock, kind="import", config={}, planned=1)
        task_b = runs.add_task(conn, clock, run_b, task_key="000000:b", query={})
        jobs.ensure(conn, clock, m.job_id, "boss", m.source_job_id, None, None)
        newer = _sighting(conn, clock, m, run_a, task_a, sha="a" * 64, observed_at=clock.now())
        _sighting(conn, clock, m, run_b, task_b, sha="b" * 64, observed_at=clock.now() - timedelta(days=1))
        jobs.refresh_current(conn, clock, m.job_id)
    j = conn.execute("select * from jobs where job_id=?", (m.job_id,)).fetchone()
    assert j["current_sighting_id"] == newer and j["hit_count"] == 2 and j["seen_run_count"] == 2

def test_unknown_observation_time_sorts_last_and_is_ignored_by_min_max(conn, clock):
    m = _mapped(0)
    with db.write_tx(conn):
        run_id = runs.create(conn, clock, kind="import", config={}, planned=2)
        task_id = runs.add_task(conn, clock, run_id, task_key="000000:x", query={})
        jobs.ensure(conn, clock, m.job_id, "boss", m.source_job_id, None, None)
        timed = _sighting(conn, clock, m, run_id, task_id, sha="c" * 64, observed_at=clock.now())
        untimed = _sighting(conn, clock, m, run_id, task_id, sha="d" * 64, observed_at=None)
        jobs.refresh_current(conn, clock, m.job_id)
    j = conn.execute("select * from jobs where job_id=?", (m.job_id,)).fetchone()
    assert j["current_sighting_id"] == timed and j["hit_count"] == 2
    assert j["first_seen_at"] == j["last_seen_at"] == iso_utc(clock.now())
    assert conn.execute("select observed_at from sightings where observation_id=?", (untimed,)).fetchone()[0] is None

def test_sighting_file_key_is_unique(conn, clock):
    m = _mapped(1)
    with db.write_tx(conn):
        run_id = runs.create(conn, clock, kind="import", config={}, planned=1)
        task_id = runs.add_task(conn, clock, run_id, task_key="000000:f", query={})
        jobs.ensure(conn, clock, m.job_id, "boss", m.source_job_id, None, None)
        _sighting(conn, clock, m, run_id, task_id, sha="e" * 64, index=5, observed_at=clock.now())
        assert sightings.exists_file_key(conn, "e" * 64, 5)
        with pytest.raises(sqlite3.IntegrityError):
            _sighting(conn, clock, m, run_id, task_id, sha="e" * 64, index=5, observed_at=clock.now())
