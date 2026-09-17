# tests/integration/test_profile_binding.py
import json, shutil
from tests.conftest import FIXTURES
L = FIXTURES / "legacy"
PROFILE = FIXTURES / "profile.synthetic.json"

def _prep(cli, wmj_home, *, profile=True):
    cli(["import", str(L / "合肥_AI产品经理.json"), str(L / "合肥_产品经理.json")])
    shutil.copy(FIXTURES / "scoring.minimal.json", wmj_home.config("scoring.json"))
    if profile:
        shutil.copy(PROFILE, wmj_home.config("profile.json"))
    rc, env, _ = cli(["match"]); assert rc == 0, env
    return env

def test_current_when_profile_revision_matches(cli, wmj_home):
    _prep(cli, wmj_home)
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa"])
    assert env["data"]["job"]["match_state"] == "current" and env["warnings"] == []
    rc, env, _ = cli(["status"])
    assert env["data"]["match"]["state"] == "current" and env["data"]["match"]["counts"]["current"] == 4
    assert env["data"]["match_input"] == {"input_selection": "latest", "input_snapshot_hash": env["data"]["match_input"]["input_snapshot_hash"]}

def test_profile_revision_change_makes_stale(cli, wmj_home):
    _prep(cli, wmj_home)
    p = json.loads(PROFILE.read_text(encoding="utf-8")); p["profile_revision"] = "synthetic-qc-to-aipm-v2"
    wmj_home.config("profile.json").write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa"])
    assert env["data"]["job"]["match_state"] == "stale" and any("画像版本已变化" in w for w in env["warnings"])
    rc, env, _ = cli(["status"])
    assert env["data"]["match"]["state"] == "stale" and env["data"]["match"]["counts"]["stale"] == 4

def test_missing_profile_is_stale_with_warning(cli, wmj_home):
    env = _prep(cli, wmj_home, profile=False)
    assert any("未找到有效画像版本" in w for w in env["warnings"])
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa"])
    assert env["data"]["job"]["match_state"] == "stale" and any("未绑定有效画像版本" in w for w in env["warnings"])

def test_broken_profile_warns_and_binds_none(cli, wmj_home):
    _prep(cli, wmj_home)
    wmj_home.config("profile.json").write_text('{"schema_version": 1}', encoding="utf-8")
    rc, env, _ = cli(["job", "list"])
    assert rc == 0 and any("profile.json" in w for w in env["warnings"])
    assert all(r["match_state"] == "stale" for r in env["data"]["jobs"])
