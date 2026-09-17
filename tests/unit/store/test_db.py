import json, os, sqlite3, stat, subprocess, sys
import pytest
from where_my_job.store import db
from where_my_job.errors import EnvError

EXPECTED_TABLES = {"jobs", "companies", "runs", "run_tasks", "sightings", "evidence", "evidence_bundles",
                   "deepdives", "match_results", "job_attrs", "network_policy_state", "schema_migrations",
                   "applications", "stream_registry", "events"}
EXPECTED_VIEWS = {"v_jobs", "v_events", "v_evidence", "v_runs"}

def _expected_versions():
    return [version for version, _, _ in db._migration_files()]

def _versions(c):
    return [row[0] for row in c.execute("select version from schema_migrations order by version")]

def test_migrate_creates_all_tables_and_views(wmj_home, clock):
    c = db.open_db(wmj_home.db_path, clock=clock)
    assert db.migrate(c, wmj_home, clock=clock) == _expected_versions()
    names = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    views = {r[0] for r in c.execute("select name from sqlite_master where type='view'")}
    assert EXPECTED_TABLES <= names and EXPECTED_VIEWS <= views
    assert _versions(c) == _expected_versions()
    assert c.execute("pragma foreign_keys").fetchone()[0] == 1
    assert stat.S_IMODE(wmj_home.db_path.stat().st_mode) == 0o600

def test_migrate_is_idempotent_without_backup(wmj_home, clock):
    c = db.open_db(wmj_home.db_path, clock=clock); db.migrate(c, wmj_home, clock=clock); c.close()
    c = db.open_db(wmj_home.db_path, clock=clock)
    assert db.migrate(c, wmj_home, clock=clock) == []
    assert _versions(c) == _expected_versions()
    assert list(wmj_home.backups.glob("*.sqlite3")) == []

def test_new_migration_is_preceded_by_0600_backup(wmj_home, clock, monkeypatch):
    c = db.open_db(wmj_home.db_path, clock=clock); db.migrate(c, wmj_home, clock=clock)
    original = db._migration_files
    monkeypatch.setattr(db, "_migration_files",
                        lambda: original() + [(9999, "9999_test.sql", "CREATE TABLE t_extra(x);")])
    assert db.migrate(c, wmj_home, clock=clock) == [9999]
    backups = list(wmj_home.backups.glob("pre-migrate-9999-*.sqlite3"))
    assert len(backups) == 1 and stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    bk = sqlite3.connect(str(backups[0]))
    tables = {r[0] for r in bk.execute("select name from sqlite_master where type='table'")}
    bk.close()
    assert "jobs" in tables and "t_extra" not in tables

@pytest.mark.skipif(os.geteuid() == 0, reason="root 忽略目录权限")
def test_backup_failure_aborts_migration(wmj_home, clock, monkeypatch):
    c = db.open_db(wmj_home.db_path, clock=clock); db.migrate(c, wmj_home, clock=clock)
    original = db._migration_files
    monkeypatch.setattr(db, "_migration_files",
                        lambda: original() + [(9999, "9999_test.sql", "CREATE TABLE t_extra(x);")])
    os.chmod(wmj_home.backups, 0o500)
    try:
        with pytest.raises(EnvError) as ei:
            db.migrate(c, wmj_home, clock=clock)
        assert ei.value.code == "PERMISSION_DENIED"
    finally:
        os.chmod(wmj_home.backups, 0o700)
    assert 9999 not in _versions(c)
    assert c.execute("select count(*) from sqlite_master where name='t_extra'").fetchone()[0] == 0

def test_checksum_mismatch_refuses_to_start(wmj_home, clock, monkeypatch):
    c = db.open_db(wmj_home.db_path, clock=clock); db.migrate(c, wmj_home, clock=clock)
    tampered = [(v, n, s + "\n-- changed") for v, n, s in db._migration_files()]
    monkeypatch.setattr(db, "_migration_files", lambda: tampered)
    with pytest.raises(EnvError) as ei:
        db.migrate(c, wmj_home, clock=clock)
    assert ei.value.code == "MISSING_DEPENDENCY"

# 回归守护：open_db 的 WAL 切换与 migrate 必须都在 state/migrations.lock 内；否则 3 进程并发首次启动约 1/4 轮失败（database is locked）。
def test_concurrent_first_migrations_serialize(tmp_path):
    env = dict(os.environ, WMJ_HOME=str(tmp_path / "shared-home"))
    script = ("import json; from where_my_job import paths; from where_my_job.store import db; "
              "lay = paths.ensure_layout(); c = db.open_db(lay.db_path); print(json.dumps(db.migrate(c, lay)))")
    procs = [subprocess.Popen([sys.executable, "-c", script], env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) for _ in range(3)]
    outs = [p.communicate(timeout=60) for p in procs]
    assert all(p.returncode == 0 for p in procs), [o[1] for o in outs]
    applied = [v for out, _ in outs for v in json.loads(out)]
    assert sorted(applied) == _expected_versions()

def test_connection_functions(wmj_home, clock):
    c = db.open_db(wmj_home.db_path, clock=clock); db.migrate(c, wmj_home, clock=clock)
    a = c.execute("select wmj_as_of()").fetchone()[0]
    clock.advance(100)
    assert c.execute("select wmj_as_of()").fetchone()[0] == a == "2026-09-14T12:00:00.000000Z"
    assert c.execute("select wmj_profile_revision()").fetchone()[0] is None
    db.bind_profile_revision(c, "rev-1")
    assert c.execute("select wmj_profile_revision()").fetchone()[0] == "rev-1"

def test_capabilities_reports_json_window_returning():
    caps = db.capabilities()
    assert caps["json1"] and caps["window_functions"] and caps["returning"] and caps["version_ok"]

def test_write_tx_rolls_back_on_error(wmj_home, clock):
    c = db.open_db(wmj_home.db_path, clock=clock); db.migrate(c, wmj_home, clock=clock)
    with pytest.raises(ValueError):
        with db.write_tx(c):
            c.execute("insert into companies(company_id, source, source_company_id, name, created_at) "
                      "values ('boss:SYNCO1','boss','SYNCO1','x','t')")
            raise ValueError("boom")
    assert c.execute("select count(*) from companies").fetchone()[0] == 0

def test_fk_enforced_and_integrity_error_not_mapped(wmj_home, clock):
    c = db.open_db(wmj_home.db_path, clock=clock); db.migrate(c, wmj_home, clock=clock)
    with pytest.raises(sqlite3.IntegrityError):
        with db.write_tx(c):
            c.execute("insert into job_attrs(job_id,key,value_json,source,updated_at) "
                      "values ('boss:NOPE','priority','\"focus\"','user','t')")

def test_sqlite_error_mapping(wmj_home, clock):
    assert db.map_sqlite_error(sqlite3.OperationalError("database is locked")).code == "DB_BUSY"
    assert db.map_sqlite_error(sqlite3.OperationalError("disk I/O error")).code == "DISK_ERROR"
    assert db.map_sqlite_error(sqlite3.OperationalError("attempt to write a readonly database")).code == "PERMISSION_DENIED"
    assert db.map_sqlite_error(sqlite3.IntegrityError("FOREIGN KEY constraint failed")) is None
    c = db.open_db(wmj_home.db_path, clock=clock); db.migrate(c, wmj_home, clock=clock)
    with pytest.raises(EnvError) as ei:
        with db.write_tx(c):
            raise sqlite3.OperationalError("database is locked")
    assert ei.value.code == "DB_BUSY"
