# tests/integration/test_attr_cmd.py
import json
from tests.conftest import FIXTURES
L = FIXTURES / "legacy"

def test_attr_roundtrip(cli):
    cli(["import", str(L / "合肥_AI产品经理.json")])
    rc, env, _ = cli(["attr", "set", "boss:SYN0001aaaa", "priority", "focus", "--source", "user"])
    assert rc == 0 and env["data"] == {"job_id": "boss:SYN0001aaaa", "key": "priority", "source": "user"}
    rc, env, _ = cli(["attr", "set", "boss:SYN0001aaaa", "custom.remote_ok", "true", "--source", "agent"])
    assert rc == 0
    rc, env, _ = cli(["attr", "set", "boss:SYN0001aaaa", "note", "面试官是校友", "--source", "user"])
    assert rc == 0
    rc, env, _ = cli(["attr", "get", "boss:SYN0001aaaa", "custom.remote_ok"])
    assert env["data"]["values"] == [{"source": "agent", "value": True, "based_on_revision": None, "updated_at": env["data"]["values"][0]["updated_at"]}]
    rc, env, _ = cli(["attr", "list", "boss:SYN0001aaaa"])
    assert {a["key"] for a in env["data"]["attrs"]} == {"priority", "custom.remote_ok", "note"}
    rc, env, _ = cli(["attr", "unset", "boss:SYN0001aaaa", "priority", "--source", "user"])
    assert rc == 0 and env["data"]["removed"] == 1
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa"])
    assert env["data"]["job"]["priority"] is None

def test_attr_value_parsing_and_rejections(cli):
    cli(["import", str(L / "合肥_AI产品经理.json")])
    rc, env, _ = cli(["attr", "set", "boss:SYN0001aaaa", "authentic", "{}", "--source", "agent"])
    assert rc == 1 and env["errors"][0]["code"] == "RESERVED_KEY"
    rc, env, _ = cli(["attr", "set", "boss:SYN0001aaaa", "score_adjustment", '{"delta": 5, "reason": "r", "match_run_id": "run_x"}', "--source", "agent"])
    assert rc == 1
    rc, env, _ = cli(["attr", "set", "boss:SYN0001aaaa", "custom.n", "not json", "--source", "user"])
    assert rc == 0
    rc, env, _ = cli(["attr", "get", "boss:SYN0001aaaa", "custom.n"])
    assert env["data"]["values"][0]["value"] == "not json"         # 非 JSON 文本按字符串存
    rc, env, _ = cli(["attr", "set", "boss:SYN0001aaaa", "custom.bad", "NaN", "--source", "user"])
    assert rc == 1 and env["errors"][0]["path"] == "$.value"        # 非有限数值拒绝，不到 SQLite 才失败
    rc, env, _ = cli(["attr", "set", "boss:NOPE", "priority", "focus", "--source", "user"])
    assert rc == 1 and env["errors"][0]["code"] == "NOT_FOUND"
