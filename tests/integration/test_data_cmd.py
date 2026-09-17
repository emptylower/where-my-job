# tests/integration/test_data_cmd.py
import sqlite3
from tests.conftest import FIXTURES
from where_my_job import paths
from where_my_job.ids import sha256_bytes

L = FIXTURES / "legacy"
A, B = str(L / "合肥_AI产品经理.json"), str(L / "合肥_产品经理.json")

def _seed(cli):
    rc, env, _ = cli(["import", A, B])
    assert rc == 0, env

def _register_panel(wmj_home, text="<html>panel</html>"):
    wmj_home.panel_latest.write_text(text)
    paths.register_managed_output(wmj_home, wmj_home.panel_latest, sha256_bytes(text.encode()))

def _count(wmj_home, sql):
    c = sqlite3.connect(str(wmj_home.db_path))
    try:
        return c.execute(sql).fetchone()[0]
    finally:
        c.close()

def test_prune_dry_run_then_real(cli, wmj_home):
    _seed(cli)
    _register_panel(wmj_home)
    rc, env, _ = cli(["data", "prune", "--raw-before", "2026-09-14T03:20:00Z", "--dry-run"])
    d = env["data"]
    assert rc == 0 and d["dry_run"] is True and d["sightings_raw_to_prune"] == 3 and d["evidence_text_to_prune"] == 0
    assert d["managed_outputs"]["would_remove"] == [str(wmj_home.panel_latest.resolve())]
    assert wmj_home.panel_latest.exists()
    assert _count(wmj_home, "select count(*) from sightings where raw_json is null") == 0
    rc, env, _ = cli(["data", "prune", "--raw-before", "2026-09-14T03:20:00Z"])
    assert rc == 0 and env["data"]["sightings_raw_pruned"] == 3 and env["data"]["policy_state_kept"] is True
    assert not wmj_home.panel_latest.exists()
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa"])
    items = env["data"]["sightings"]["items"]
    assert sorted(x["raw_pruned"] for x in items) == [0, 1] and env["data"]["job"]["hit_count"] == 2
    rc, env, _ = cli(["status"])
    assert env["data"]["retention"]["raw_pruned_before"] == "2026-09-14T03:19:31.241776Z"

def test_prune_requires_zoned_time(cli):
    rc, env, _ = cli(["data", "prune", "--raw-before", "yesterday"])
    assert rc == 1 and env["errors"][0]["path"] == "$.raw_before"
    rc, env, _ = cli(["data", "prune", "--raw-before", "2026-09-14T03:20:00"])
    assert rc == 1

def test_delete_job_removes_only_that_job(cli, wmj_home):
    _seed(cli)
    rc, env, _ = cli(["data", "delete", "--job", "boss:SYN0002bbbb", "--dry-run"])
    assert rc == 0 and env["data"]["dry_run"] is True and env["data"]["would_delete"]["sightings"] == 1
    assert _count(wmj_home, "select count(*) from jobs") == 4
    rc, env, _ = cli(["data", "delete", "--job", "boss:SYN0002bbbb"])
    assert rc == 0 and env["data"]["deleted"]["jobs"] == 1
    rc, env, _ = cli(["job", "show", "boss:SYN0002bbbb"])
    assert rc == 1
    rc, env, _ = cli(["status"])
    assert env["data"]["counts"]["jobs"] == 3 and env["data"]["counts"]["companies"] == 2

def test_delete_all_keeps_policy_state_and_builtin_streams_and_clears_artifacts(cli, wmj_home, clock):
    _seed(cli)
    _register_panel(wmj_home)
    backup = wmj_home.backups / "pre-migrate-0002-x.sqlite3"; backup.write_bytes(b"db")
    c = sqlite3.connect(str(wmj_home.db_path))
    c.execute("insert into network_policy_state(browser_profile_id, cooldown_until, updated_at) "
              "values ('p','2026-09-15T00:00:00.000000Z','t')")
    c.execute("insert or ignore into stream_registry(stream, stream_revision, definition_json, content_hash, registered_at, is_active) "
              "values ('applications',1,'{}','h','t',1)")
    c.execute("insert into stream_registry(stream, stream_revision, definition_json, content_hash, registered_at, is_active) "
              "values ('custom.diary',1,'{}','h','t',1)")
    c.commit(); c.close()
    rc, env, _ = cli(["data", "delete", "--all"])
    d = env["data"]
    assert rc == 0 and d["deleted"]["jobs"] == 4 and d["policy_state_kept"] is True
    assert d["managed_outputs"]["removed"] == [str(wmj_home.panel_latest.resolve())]
    assert d["migration_backups"]["removed"] == [str(backup)]
    assert not wmj_home.panel_latest.exists() and not backup.exists()
    rc, env, _ = cli(["status"])
    assert env["data"]["counts"]["jobs"] == 0
    assert env["data"]["network"]["cooldown_until"] == "2026-09-15T00:00:00.000000Z"
    assert _count(wmj_home, "select count(*) from stream_registry where stream='applications'") == 1
    assert _count(wmj_home, "select count(*) from stream_registry where stream like 'custom.%'") == 0

def test_user_modified_output_is_kept_and_result_is_partial(cli, wmj_home):
    _seed(cli)
    _register_panel(wmj_home)
    wmj_home.panel_latest.write_text("user edited")
    rc, env, _ = cli(["data", "delete", "--all"])
    assert rc == 4 and env["errors"][0]["code"] == "PARTIAL_RESULT"
    assert env["data"]["managed_outputs"]["kept_modified"] == [str(wmj_home.panel_latest.resolve())]
    assert wmj_home.panel_latest.read_text() == "user edited"
    assert _count(wmj_home, "select count(*) from jobs") == 0

def test_dry_run_changes_nothing(cli, wmj_home):
    _seed(cli)
    _register_panel(wmj_home)
    backup = wmj_home.backups / "pre-migrate-0002-y.sqlite3"; backup.write_bytes(b"db")
    manifest_before = wmj_home.managed_outputs_path.read_bytes()
    rc, env, _ = cli(["data", "delete", "--all", "--dry-run"])
    assert rc == 0 and env["data"]["would_delete"]["jobs"] == 4
    assert env["data"]["migration_backups"]["would_remove"] == [str(backup)]
    assert wmj_home.panel_latest.exists() and backup.exists()
    assert wmj_home.managed_outputs_path.read_bytes() == manifest_before
    assert _count(wmj_home, "select count(*) from jobs") == 4 and _count(wmj_home, "select count(*) from sightings") == 5
