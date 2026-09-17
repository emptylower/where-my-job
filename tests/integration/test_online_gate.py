# tests/integration/test_online_gate.py
import json, pathlib
import pytest
from where_my_job import release
from tests.conftest import FIXTURES

REPO = pathlib.Path(__file__).resolve().parents[2]
STRATEGY = str(REPO / "skill" / "examples" / "strategy.first-page.json")
L = FIXTURES / "legacy"

def _write_settings(wmj_home, obj):
    wmj_home.config("settings.json").write_text(json.dumps(obj), encoding="utf-8")

def test_scan_blocked_when_default_disabled(cli, wmj_home, monkeypatch):
    monkeypatch.setattr(release, "ONLINE_ADAPTER_DEFAULT", "disabled")
    rc, env, _ = cli(["scan", "--strategy", STRATEGY])
    assert rc == 2 and env["errors"][0]["code"] == "ONLINE_DISABLED"

def test_scan_dry_run_still_works_when_disabled(cli, wmj_home, monkeypatch):
    monkeypatch.setattr(release, "ONLINE_ADAPTER_DEFAULT", "disabled")
    rc, env, _ = cli(["scan", "--strategy", STRATEGY, "--dry-run"])
    assert rc == 0 and env["data"]["planned_actions"] == 1

def test_user_settings_can_disable_even_if_default_enabled(cli, wmj_home, monkeypatch):
    monkeypatch.setattr(release, "ONLINE_ADAPTER_DEFAULT", "enabled")
    _write_settings(wmj_home, {"schema_version": 1, "online_adapter": "disabled"})
    rc, env, _ = cli(["init", "--browser"])
    assert rc == 2 and env["errors"][0]["code"] == "ONLINE_DISABLED"

def test_user_settings_cannot_enable_when_default_disabled(cli, wmj_home, monkeypatch):
    monkeypatch.setattr(release, "ONLINE_ADAPTER_DEFAULT", "disabled")
    _write_settings(wmj_home, {"schema_version": 1, "online_adapter": "enabled"})
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 2 and env["errors"][0]["code"] == "ONLINE_DISABLED"
    assert "发布门槛" in env["errors"][0]["message"]

def test_probe_is_gated_before_any_launcher(cli, wmj_home, monkeypatch):
    from where_my_job.service import browser
    monkeypatch.setattr(release, "ONLINE_ADAPTER_DEFAULT", "disabled")
    def forbidden(layout):
        raise AssertionError("launcher must not be created while online is disabled")
    monkeypatch.setattr(browser, "make_launcher", forbidden)
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 2 and env["errors"][0]["code"] == "ONLINE_DISABLED"

def test_deepdive_cached_not_gated(cli, wmj_home, monkeypatch):
    monkeypatch.setattr(release, "ONLINE_ADAPTER_DEFAULT", "disabled")
    rc, env, _ = cli(["deepdive", "boss:SYN0001aaaa", "--cached"])
    assert rc == 1 and env["errors"][0]["code"] != "ONLINE_DISABLED"   # 走到 NOT_FOUND，而不是被门禁挡

def test_deepdive_online_is_gated_before_acquire(cli, wmj_home, monkeypatch):
    from where_my_job.service import deepdive
    monkeypatch.setattr(release, "ONLINE_ADAPTER_DEFAULT", "disabled")
    rc, env, _ = cli(["import", str(L / "合肥_AI产品经理.json")])
    assert rc == 0, env
    def forbidden(ctx, job_id, *, skip_company):
        raise AssertionError("_acquire must not run while online is disabled")
    monkeypatch.setattr(deepdive, "_acquire", forbidden)
    rc, env, _ = cli(["deepdive", "boss:SYN0001aaaa"])
    assert rc == 2 and env["errors"][0]["code"] == "ONLINE_DISABLED"

def test_settings_schema_accepts_online_adapter_only_enum(cli, tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"schema_version": 1, "online_adapter": "maybe"}))
    rc, env, _ = cli(["validate", "settings", str(p)])
    assert rc == 1 and env["errors"][0]["path"] == "$.online_adapter"

def test_browser_stop_remains_available_when_online_is_disabled(cli, monkeypatch):
    from where_my_job.service import browser
    calls = []
    class OwnedLauncher:
        def stop(self):
            calls.append("verified-stop")
            return {"stopped": True, "pid": 4242}
    monkeypatch.setattr(release, "ONLINE_ADAPTER_DEFAULT", "disabled")
    monkeypatch.setattr(browser, "make_launcher", lambda layout: OwnedLauncher())
    rc, env, _ = cli(["browser", "stop"])
    assert rc == 0
    assert env["data"] == {"stopped": True, "pid": 4242}
    assert calls == ["verified-stop"]

def test_login_start_and_status_are_gated_before_launcher(cli, wmj_home, monkeypatch):
    from where_my_job.service import login
    monkeypatch.setattr(release, "ONLINE_ADAPTER_DEFAULT", "disabled")
    def forbidden(layout):
        raise AssertionError("launcher must not be created while online is disabled")
    monkeypatch.setattr(login, "make_launcher", forbidden)
    for argv in (["login", "start"], ["login", "status"]):
        rc, env, _ = cli(argv)
        assert rc == 2 and env["errors"][0]["code"] == "ONLINE_DISABLED"
