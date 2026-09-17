# tests/integration/test_examples_roundtrip.py
import json, re
from tests.conftest import FIXTURES
from where_my_job.store import db

REPO = FIXTURES.parents[2]
EVENT_DOC = REPO / "skill" / "references" / "event-schema.md"
L = FIXTURES / "legacy"

def _event_examples() -> dict:
    text = EVENT_DOC.read_text(encoding="utf-8")
    blocks = re.findall(r"<!-- schema: event -->\s*```json\n(.*?)\n```", text, re.S)
    objs = [json.loads(b) for b in blocks]
    return {o["type"]: o for o in objs}

def _write(tmp_path, name, obj) -> str:
    p = tmp_path / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return str(p)

def test_event_examples_roundtrip_through_real_service(cli, tmp_path, wmj_home, clock):
    rc, env, _ = cli(["import", str(L / "合肥_AI产品经理.json"), str(L / "合肥_产品经理.json")])
    assert rc == 0, env
    examples = _event_examples()
    assert set(examples) == {"applied", "corrected"}

    rc, env, _ = cli(["event", "add", "--file", _write(tmp_path, "applied.json", examples["applied"])])
    assert rc == 0, env
    applied = env["data"]
    assert applied["created"] is True and applied["application_id"].startswith("app_")
    assert applied["root_event_id"] == applied["current_event_id"]

    corrected = json.loads(json.dumps(examples["corrected"]))
    corrected["subject_id"] = applied["application_id"]
    corrected["corrected"]["corrected_event_id"] = applied["current_event_id"]
    corrected_path = _write(tmp_path, "corrected.json", corrected)

    clock.advance(60)                      # 只在插入新的语义事件前推进时钟；重试不推进
    rc, env, _ = cli(["event", "add", "--file", corrected_path])
    assert rc == 0, env
    first = env["data"]
    assert first["created"] is True and first["root_event_id"] == applied["root_event_id"]

    rc, env, _ = cli(["event", "add", "--file", corrected_path])
    assert rc == 0, env
    again = env["data"]
    assert again["created"] is False and again["event_id"] == first["event_id"]

    conn = db.open_db(wmj_home.db_path, clock=clock)
    try:
        count = conn.execute(
            "select count(*) from events where type='corrected' and subject_kind='application' and subject_id=?",
            (applied["application_id"],)).fetchone()[0]
    finally:
        conn.close()
    assert count == 1
