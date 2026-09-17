import json
from tests.conftest import FIXTURES
from where_my_job.store import db, runs

A = str(FIXTURES / "legacy" / "合肥_AI产品经理.json")

def _expected_versions():
    return [version for version, _, _ in db._migration_files()]

def test_init_local_creates_layout_and_db(cli, wmj_home):
    rc, env, _ = cli(["init"])
    assert rc == 0 and env["data"]["home"] == str(wmj_home.root)
    assert env["data"]["db"]["migrations_applied"] == _expected_versions()
    assert env["data"]["db"]["schema_version"] == max(_expected_versions())
    assert env["data"]["sqlite"]["json1"] is True and env["data"]["browser"] == {"requested": False}
    assert env["data"]["recovered_runs"] == [] and wmj_home.db_path.exists()

def test_init_is_idempotent(cli):
    cli(["init"])
    rc, env, _ = cli(["init"])
    assert rc == 0 and env["data"]["db"]["migrations_applied"] == []
    assert env["data"]["db"]["schema_version"] == max(_expected_versions())

def test_status_reports_counts_retention_and_no_network(cli):
    cli(["import", A])
    rc, env, _ = cli(["status"])
    d = env["data"]
    assert rc == 0
    assert d["counts"] == {"jobs": 3, "sightings": 3, "companies": 2, "evidence": 0, "reports": 0, "events": 0}
    assert d["retention"] == {"policy": "no_expiry", "raw_pruned_before": None, "last_prune_at": None}
    assert d["observations"] == {"earliest": "2026-09-14T03:19:31.241776Z", "latest": "2026-09-14T03:19:31.241776Z",
                                 "unknown_time_count": 0}
    assert d["runs"]["last_import"]["status"] == "ok" and d["runs"]["running"] == []
    assert d["match"] == {"current_run_id": None, "state": "missing",
                          "counts": {"missing": 3, "current": 0, "stale": 0}}
    assert d["reports"] == {"pending_bundles": 0}
    assert d["network"] == {"lock_held": False, "cooldown_until": None, "actions_last_24h": 0, "budget_24h": 80}
    assert d["db_size_bytes"] > 0 and d["as_of"] == "2026-09-14T12:00:00.000000Z"

def test_status_is_read_only_and_init_recovers_only_orphans_with_owner_file(cli, wmj_home, clock):
    cli(["init"])
    c = db.open_db(wmj_home.db_path, clock=clock)
    with db.write_tx(c):
        ownerless = runs.create(c, clock, kind="import", config={}, planned=1)
        orphan = runs.create(c, clock, kind="import", config={}, planned=1)
    c.close()
    orphan_lock = wmj_home.runs_dir / f"{orphan}.lock"
    orphan_lock.write_bytes(b"")                      # 所有者文件存在但无人持锁：前次进程已退出
    for _ in range(3):
        rc, env, _ = cli(["status"])
        assert rc == 0 and sorted(env["data"]["runs"]["running"]) == sorted([ownerless, orphan])
    assert orphan_lock.exists()
    rc, env, _ = cli(["init"])
    assert rc == 0 and env["data"]["recovered_runs"] == [orphan]
    assert any(ownerless in w and "缺少所有者锁文件" in w for w in env["warnings"])
    rc, env, _ = cli(["status"])
    assert env["data"]["runs"]["running"] == [ownerless]
