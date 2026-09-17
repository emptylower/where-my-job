# tests/unit/test_version_online_default.py
from where_my_job import release

def test_version_reports_online_adapter_release_default(cli, monkeypatch):
    rc, env, _ = cli(["version"])
    assert rc == 0 and env["data"]["online_adapter_default"] == release.ONLINE_ADAPTER_DEFAULT
    monkeypatch.setattr(release, "ONLINE_ADAPTER_DEFAULT", "enabled")
    rc, env, _ = cli(["version"])
    assert rc == 0 and env["data"] == {"version": env["data"]["version"], "online_adapter_default": "enabled"}
