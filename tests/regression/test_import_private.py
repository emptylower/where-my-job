# tests/regression/test_import_private.py
import json

def test_42_files_yield_1260_obs_1225_jobs_and_reimport_is_noop(cli, private_manifest):
    rc, env, _ = cli(["import", "--manifest", private_manifest])
    assert rc == 0, env
    d = env["data"]
    assert d["files_ok"] == 42 and d["observations_inserted"] == 1260 and d["jobs_total"] == 1225
    assert d["record_errors"] == 0 and d["files_failed"] == []
    rc, env, _ = cli(["import", "--manifest", private_manifest])
    assert rc == 0 and env["data"]["observations_inserted"] == 0 and env["data"]["observations_skipped"] == 1260
    rc, env, _ = cli(["status"])
    counts = env["data"]["counts"]
    assert (counts["jobs"], counts["sightings"], counts["evidence"], counts["reports"], counts["events"]) == (1225, 1260, 0, 0, 0)
    assert env["data"]["observations"]["unknown_time_count"] == 0

def test_multi_hit_jobs(cli, private_manifest):
    cli(["import", "--manifest", private_manifest])
    rc, env, _ = cli(["job", "list", "--filter", "hit_count>=2", "--page-size", "500"])
    assert rc == 0 and env["data"]["total"] == 34

def test_stdout_never_contains_private_fields(cli, private_manifest):
    cli(["import", "--manifest", private_manifest])
    rc, env, _ = cli(["job", "list", "--page-size", "500"])
    text = json.dumps(env, ensure_ascii=False)
    for bad in ("securityId", "security_id", '"lid"', "encrypt_boss_id", "raw_json"):
        assert bad not in text
