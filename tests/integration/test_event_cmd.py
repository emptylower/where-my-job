# tests/integration/test_event_cmd.py
import json
from tests.conftest import FIXTURES
E, S, L = FIXTURES / "events", FIXTURES / "streams", FIXTURES / "legacy"

def _file(tmp_path, name, **subst):
    text = (E / name).read_text(encoding="utf-8")
    for k, v in subst.items(): text = text.replace(k, v)
    p = tmp_path / name; p.write_text(text, encoding="utf-8"); return str(p)

def _add(cli, clock, path):
    clock.advance(1)                       # 新语义事件前推进时钟；重试调用直接用 cli
    return cli(["event", "add", "--file", path])

def _seed(cli, clock, tmp_path):
    cli(["import", str(L / "合肥_AI产品经理.json")])
    cli(["stream", "register", "--file", str(S / "custom.interviews.v1.json")])
    rc, env, _ = _add(cli, clock, _file(tmp_path, "applied.json"))
    assert rc == 0, env
    return env["data"]["application_id"]

def test_applied_replied_timeline_and_v_jobs(cli, clock, tmp_path):
    app = _seed(cli, clock, tmp_path)
    rc, env, _ = _add(cli, clock, _file(tmp_path, "replied.json", APP_ID_PLACEHOLDER=app))
    assert rc == 0 and env["data"]["created"] is True and env["data"]["root_event_id"] == env["data"]["current_event_id"]
    rc, env, _ = cli(["event", "list", "--stream", "applications", "--subject", app])
    assert [e["type"] for e in env["data"]["events"]] == ["applied", "replied"]
    assert env["data"]["events"][0]["occurred_at"] == "2026-09-10T08:00:00.000000Z"
    assert env["data"]["page"] == {"total": 2, "limit": 1000, "offset": 0, "truncated": False}
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa"])
    j = env["data"]["job"]
    assert j["application_id"] == app and j["application_state"] == "replied" and j["followup_due"] == 0

def test_followup_due_after_72h_without_reply(cli, clock, tmp_path):
    _seed(cli, clock, tmp_path)                # applied 2026-09-10T08Z；as_of 固定约 2026-09-14T12Z
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa"])
    assert env["data"]["job"]["application_state"] == "applied" and env["data"]["job"]["followup_due"] == 1

def test_validate_event_uses_same_helper_and_does_not_write(cli, clock, tmp_path):
    app = _seed(cli, clock, tmp_path)
    rc, env, _ = cli(["validate", "event", _file(tmp_path, "scheduled.json", APP_ID_PLACEHOLDER=app)])
    assert rc == 0
    rc, env, _ = cli(["validate", "event", _file(tmp_path, "scheduled.json", APP_ID_PLACEHOLDER="app_404")])
    assert rc == 1 and env["errors"][0]["code"] == "SUBJECT_MISSING"
    rc, env, _ = cli(["event", "list", "--stream", "custom.interviews"])
    assert env["data"]["events"] == [] and env["data"]["page"]["total"] == 0      # validate 不写

def test_validate_event_after_upgrade_old_request_ok_new_request_needs_active(cli, clock, tmp_path):
    app = _seed(cli, clock, tmp_path)
    sched = _file(tmp_path, "scheduled.json", APP_ID_PLACEHOLDER=app)
    assert _add(cli, clock, sched)[0] == 0
    assert cli(["stream", "register", "--file", str(S / "custom.interviews.v2.json")])[0] == 0
    rc, env, _ = cli(["validate", "event", sched])                      # 已成功请求：按其绑定版本比较，不要求活动版本
    assert rc == 0
    d = json.loads((tmp_path / "scheduled.json").read_text()); d["idempotency_key"] = "syn-sched-0002"
    p = tmp_path / "new-old-rev.json"; p.write_text(json.dumps(d, ensure_ascii=False))
    rc, env, _ = cli(["validate", "event", str(p)])
    assert rc == 1 and env["errors"][0]["path"] == "$.stream_revision"

def test_custom_stream_add_retract_history(cli, clock, tmp_path):
    app = _seed(cli, clock, tmp_path)
    rc, env, _ = _add(cli, clock, _file(tmp_path, "scheduled.json", APP_ID_PLACEHOLDER=app))
    assert rc == 0; root = env["data"]["root_event_id"]
    rc, env, _ = cli(["event", "list", "--stream", "custom.interviews", "--subject", app])
    e = env["data"]["events"][0]
    assert e["fields"]["format"] == {"present": True, "value": "video"} and e["stream_revision"] == 1
    rc, env, _ = _add(cli, clock, _file(tmp_path, "retract-scheduled.json", APP_ID_PLACEHOLDER=app, EVENT_ID_PLACEHOLDER=root))
    assert rc == 0 and env["data"]["root_event_id"] == root and env["data"]["current_event_id"] != root
    rc, env, _ = cli(["event", "list", "--stream", "custom.interviews", "--subject", app])
    assert env["data"]["events"] == []
    rc, env, _ = cli(["event", "list", "--stream", "custom.interviews", "--subject", app, "--history"])
    assert [h["type"] for h in env["data"]["history"]] == ["scheduled", "corrected"] and env["data"]["history"][1]["op"] == "retract"
    assert env["data"]["history_page"] == {"total": 2, "limit": 2000, "offset": 0, "truncated": False}

def test_event_list_paging_options_and_validation(cli, clock, tmp_path):
    app = _seed(cli, clock, tmp_path)
    assert _add(cli, clock, _file(tmp_path, "replied.json", APP_ID_PLACEHOLDER=app))[0] == 0
    rc, env, _ = cli(["event", "list", "--stream", "applications", "--limit", "1"])
    assert rc == 0 and len(env["data"]["events"]) == 1 and env["data"]["page"] == {"total": 2, "limit": 1, "offset": 0, "truncated": True}
    rc, env, _ = cli(["event", "list", "--stream", "applications", "--limit", "1", "--offset", "1"])
    assert env["data"]["events"][0]["type"] == "replied" and env["data"]["page"]["truncated"] is False
    rc, env, _ = cli(["event", "list", "--stream", "applications", "--limit", "0"])
    assert rc == 1 and env["errors"][0]["code"] == "SEMANTIC_INVALID" and env["errors"][0]["path"] == "$.limit"
    rc, env, _ = cli(["event", "list", "--stream", "applications", "--history", "--history-limit", "2001"])
    assert rc == 1 and env["errors"][0]["path"] == "$.limit"
    rc, env, _ = cli(["event", "list", "--stream", "custom.nope"])
    assert rc == 1 and env["errors"][0]["code"] == "NOT_FOUND"

def test_idempotent_retry_and_conflict_via_cli(cli, clock, tmp_path):
    app = _seed(cli, clock, tmp_path)
    rc, env, _ = cli(["event", "add", "--file", str(tmp_path / "applied.json")])        # 重试：不推进时钟
    assert rc == 0 and env["data"]["created"] is False and env["data"]["application_id"] == app
    p = tmp_path / "applied.json"; d = json.loads(p.read_text()); d["payload"]["note"] = "x"; p.write_text(json.dumps(d, ensure_ascii=False))
    rc, env, _ = cli(["event", "add", "--file", str(p)])
    assert rc == 1 and env["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"

def test_event_errors_have_paths_and_no_half_write(cli, clock, tmp_path):
    app = _seed(cli, clock, tmp_path)
    d = json.loads((E / "scheduled.json").read_text()); d["subject_id"] = app; d["payload"] = {"round": 1}
    bad = tmp_path / "bad.json"; bad.write_text(json.dumps(d))
    rc, env, _ = cli(["event", "add", "--file", str(bad)])
    assert rc == 1 and {e["path"] for e in env["errors"]} >= {"$.payload.round", "$.payload.at"}
    d2 = json.loads((E / "scheduled.json").read_text()); d2["subject_id"] = app; d2.pop("stream_revision")
    nover = tmp_path / "nover.json"; nover.write_text(json.dumps(d2))
    rc, env, _ = cli(["event", "add", "--file", str(nover)])
    assert rc == 1 and env["errors"][0]["code"] == "SCHEMA_INVALID"
    rc, env, _ = cli(["status"]); assert env["data"]["counts"]["events"] == 1
