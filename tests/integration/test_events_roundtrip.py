# tests/integration/test_events_roundtrip.py
"""D11–D15 门槛：首次 applied → 回复 → 面试（自定义流）→ 纠错 → 升版 → 旧事件按旧声明读取 → 重试幂等。"""
import json
from tests.conftest import FIXTURES
from where_my_job.clock import iso_utc
E, S, L = FIXTURES / "events", FIXTURES / "streams", FIXTURES / "legacy"

def _add(cli, clock, tmp_path, obj, name, new=True):
    p = tmp_path / name; p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    if new:
        clock.advance(1)
    return cli(["event", "add", "--file", str(p)])

def test_full_loop(cli, clock, tmp_path):
    cli(["import", str(L / "合肥_AI产品经理.json")])
    assert cli(["stream", "register", "--file", str(S / "custom.interviews.v1.json")])[0] == 0
    applied = json.loads((E / "applied.json").read_text())
    rc, env, _ = _add(cli, clock, tmp_path, applied, "a.json"); app = env["data"]["application_id"]
    replied = json.loads((E / "replied.json").read_text()); replied["subject_id"] = app
    assert _add(cli, clock, tmp_path, replied, "r.json")[0] == 0
    sched = json.loads((E / "scheduled.json").read_text()); sched["subject_id"] = app
    rc, env, _ = _add(cli, clock, tmp_path, sched, "s.json"); sched_root = env["data"]["root_event_id"]
    # 纠错：面试改期（replace）。纠错记录自己的发生时间与被替代事实的时间不同
    fix = {"schema_version": 1, "stream": "custom.interviews", "stream_revision": 1, "type": "corrected", "subject_kind": "application",
           "subject_id": app, "occurred_at": "2026-09-13T09:00:00+08:00", "payload": {}, "idempotency_key": "syn-fix-0001", "origin": "user",
           "corrected": {"corrected_event_id": sched_root, "op": "replace", "original_type": "scheduled",
                         "replacement_payload": {"round": "1", "at": "2026-09-16T10:00:00+08:00", "format": "video"},
                         "replacement_occurred_at": sched["occurred_at"]}}
    rc, env, _ = _add(cli, clock, tmp_path, fix, "f.json"); assert rc == 0 and env["data"]["root_event_id"] == sched_root
    rc, env, _ = _add(cli, clock, tmp_path, fix, "f2.json", new=False)
    assert rc == 0 and env["data"]["created"] is False                  # 纠错重试幂等
    # 升版后旧事件按旧声明读取；新事件绑定新活动版本
    assert cli(["stream", "register", "--file", str(S / "custom.interviews.v2.json")])[0] == 0
    cancel = {"schema_version": 1, "stream": "custom.interviews", "stream_revision": 2, "type": "cancelled", "subject_kind": "application",
              "subject_id": app, "occurred_at": "2026-09-16T00:00:00Z", "payload": {"round": "2", "reason": "me"},
              "idempotency_key": "syn-cancel-0001", "origin": "user"}
    assert _add(cli, clock, tmp_path, cancel, "c.json")[0] == 0
    rc, env, _ = cli(["event", "list", "--stream", "custom.interviews", "--subject", app])
    ev = env["data"]["events"]
    assert [e["type"] for e in ev] == ["scheduled", "cancelled"]
    assert ev[0]["stream_revision"] == 1 and "interviewer_title" not in ev[0]["fields"]
    assert ev[0]["fields"]["at"]["value"] == "2026-09-16T10:00:00+08:00" and ev[0]["corrected"] is True
    assert ev[1]["stream_revision"] == 2 and ev[1]["fields"]["reason"]["value"] == "me"
    # 升版后重试旧请求（仍绑定 revision 1）幂等
    rc, env, _ = _add(cli, clock, tmp_path, sched, "s2.json", new=False)
    assert rc == 0 and env["data"]["created"] is False and env["data"]["root_event_id"] == sched_root
    # 投递状态
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa"])
    assert env["data"]["job"]["application_state"] == "replied" and env["data"]["job"]["followup_due"] == 0
    # 读命令不做写侧恢复：遗留 running 的 run 保持原状，事件不受影响
    from where_my_job.store import db
    import where_my_job.paths as paths
    lay = paths.ensure_layout()
    c = db.open_db(lay.db_path, clock=clock)
    c.execute("insert into runs(run_id,kind,status,config_json,config_hash,started_at) values ('run_zombie','match','running','{}','h',?)",
              (iso_utc(clock.now()),))
    c.close()
    rc, env, _ = cli(["status"])
    assert rc == 0 and env["data"]["counts"]["events"] == 5
    c = db.open_db(lay.db_path, clock=clock)
    assert c.execute("select status from runs where run_id='run_zombie'").fetchone()[0] == "running"
    c.close()
