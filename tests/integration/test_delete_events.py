# tests/integration/test_delete_events.py
import json
from tests.conftest import FIXTURES
E, S, L = FIXTURES / "events", FIXTURES / "streams", FIXTURES / "legacy"

def _ev(cli, clock, tmp_path, name, **subst):
    text = (E / name).read_text(encoding="utf-8")
    for k, v in subst.items(): text = text.replace(k, v)
    p = tmp_path / name; p.write_text(text, encoding="utf-8")
    clock.advance(1)
    rc, env, _ = cli(["event", "add", "--file", str(p)]); assert rc == 0, env; return env["data"]

def test_delete_job_removes_its_chain_but_not_sibling_under_same_company(cli, clock, tmp_path):
    # 两个岗位共享公司 SYNCO1：合肥_AI产品经理 的 SYN0001aaaa 与 合肥_产品经理 的 SYN0004dddd（子计划 01 Task 7 的 fixture）
    cli(["import", str(L / "合肥_AI产品经理.json"), str(L / "合肥_产品经理.json")])
    cli(["stream", "register", "--file", str(S / "custom.interviews.v1.json")])
    a = _ev(cli, clock, tmp_path, "applied.json")
    app = a["application_id"]
    s = _ev(cli, clock, tmp_path, "scheduled.json", APP_ID_PLACEHOLDER=app)
    _ev(cli, clock, tmp_path, "retract-scheduled.json", APP_ID_PLACEHOLDER=app, EVENT_ID_PLACEHOLDER=s["root_event_id"])
    d = json.loads((E / "applied.json").read_text()); d["payload"]["job_id"] = "boss:SYN0004dddd"; d["idempotency_key"] = "syn-applied-0004"
    p = tmp_path / "applied4.json"; p.write_text(json.dumps(d, ensure_ascii=False))
    clock.advance(1)
    assert cli(["event", "add", "--file", str(p)])[0] == 0
    rc, env, _ = cli(["data", "delete", "--job", "boss:SYN0001aaaa", "--dry-run"])
    assert env["data"]["would_delete"]["events"] == 3 and env["data"]["would_delete"]["applications"] == 1
    rc, env, _ = cli(["data", "delete", "--job", "boss:SYN0001aaaa"]); assert rc == 0
    rc, env, _ = cli(["status"])
    assert env["data"]["counts"]["events"] == 1 and env["data"]["counts"]["companies"] >= 1
    rc, env, _ = cli(["event", "list", "--stream", "applications"])
    assert len(env["data"]["events"]) == 1 and env["data"]["events"][0]["fields"]["job_id"]["value"] == "boss:SYN0004dddd"
    rc, env, _ = cli(["event", "list", "--stream", "custom.interviews", "--history"])
    assert env["data"]["history"] == [] and env["data"]["history_page"]["total"] == 0
    rc, env, _ = cli(["stream", "list"]); assert any(x["stream"] == "custom.interviews" for x in env["data"]["streams"])
