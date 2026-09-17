# tests/integration/test_validate_cmd.py
import json

def test_validate_settings_ok_and_bad(cli, tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"schema_version": 1, "timezone": "Asia/Shanghai"}))
    rc, env, _ = cli(["validate", "settings", str(p)])
    assert rc == 0 and env["data"] == {"kind": "settings", "issues": []}
    p.write_text(json.dumps({"schema_version": 1, "retention_days": 7}))
    rc, env, _ = cli(["validate", "settings", str(p)])
    assert rc == 1 and env["errors"][0]["code"] == "UNSUPPORTED_SETTING"

def test_validate_rejects_non_finite_and_unknown_kind(cli, tmp_path):
    p = tmp_path / "s.json"
    p.write_text('{"schema_version": 1, "page_size": NaN}')
    rc, env, _ = cli(["validate", "settings", str(p)])
    assert rc == 1 and env["errors"][0]["code"] == "SCHEMA_INVALID"
    rc, env, _ = cli(["validate", "resume", str(p)])
    assert rc == 1

def test_validate_reads_file_once(cli, tmp_path, monkeypatch):
    from where_my_job.config import loader
    calls = []
    original = loader.read_json_file
    monkeypatch.setattr(loader, "read_json_file", lambda path: calls.append(path) or original(path))
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"schema_version": 1}))
    rc, env, _ = cli(["validate", "settings", str(p)])
    assert rc == 0 and len(calls) == 1
