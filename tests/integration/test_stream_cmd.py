# tests/integration/test_stream_cmd.py
from tests.conftest import FIXTURES
S = FIXTURES / "streams"

def test_validate_does_not_activate_register_does(cli):
    rc, env, _ = cli(["validate", "stream", str(S / "custom.interviews.v1.json")])
    assert rc == 0 and env["data"]["issues"] == []
    rc, env, _ = cli(["stream", "list"])
    assert [s["stream"] for s in env["data"]["streams"]] == ["applications"]
    rc, env, _ = cli(["stream", "register", "--file", str(S / "custom.interviews.v1.json")])
    assert rc == 0 and env["data"] == {"stream": "custom.interviews", "stream_revision": 1, "content_hash": env["data"]["content_hash"], "created": True}
    rc, env, _ = cli(["stream", "list"])
    assert [(s["stream"], s["stream_revision"]) for s in env["data"]["streams"]] == [("applications", 1), ("custom.interviews", 1)]

def test_register_upgrade_and_show_revision(cli):
    cli(["stream", "register", "--file", str(S / "custom.interviews.v1.json")])
    rc, env, _ = cli(["stream", "register", "--file", str(S / "custom.interviews.v2.json")])
    assert rc == 0 and env["data"]["stream_revision"] == 2
    rc, env, _ = cli(["stream", "show", "custom.interviews"])
    assert env["data"]["stream_revision"] == 2 and env["data"]["is_active"] is True and "cancelled" in env["data"]["definition"]["types"]
    rc, env, _ = cli(["stream", "show", "custom.interviews", "--revision", "1"])
    assert env["data"]["stream_revision"] == 1 and env["data"]["is_active"] is False
    assert [r["stream_revision"] for r in env["data"]["revisions"]] == [1, 2]

def test_incompatible_upgrade_exit_1_with_path(cli):
    cli(["stream", "register", "--file", str(S / "custom.interviews.v1.json")])
    rc, env, _ = cli(["stream", "register", "--file", str(S / "custom.interviews.v2-incompatible.json")])
    assert rc == 1 and env["errors"][0]["code"] == "INCOMPATIBLE_REVISION" and env["errors"][0]["path"] == "$.types"
    rc, env, _ = cli(["stream", "show", "custom.interviews"]); assert env["data"]["stream_revision"] == 1

def test_projection_unsupported(cli):
    rc, env, _ = cli(["stream", "register", "--file", str(S / "custom.bad-projection.json")])
    assert rc == 1 and env["errors"][0]["code"] == "UNSUPPORTED_SETTING" and env["errors"][0]["path"] == "$.projection"

def test_overwriting_file_does_not_activate(cli, tmp_path):
    import shutil
    p = tmp_path / "s.json"; shutil.copy(S / "custom.interviews.v1.json", p)
    cli(["stream", "register", "--file", str(p)])
    p.write_text((S / "custom.interviews.v2.json").read_text())
    rc, env, _ = cli(["stream", "show", "custom.interviews"]); assert env["data"]["stream_revision"] == 1

def test_register_bad_json_is_schema_invalid(cli, tmp_path):
    p = tmp_path / "bad.json"; p.write_text("{oops", encoding="utf-8")
    rc, env, _ = cli(["stream", "register", "--file", str(p)])
    assert rc == 1 and env["errors"][0]["code"] == "SCHEMA_INVALID"

def test_show_unknown_stream(cli):
    rc, env, _ = cli(["stream", "show", "custom.nope"])
    assert rc == 1 and env["errors"][0]["code"] == "NOT_FOUND"
