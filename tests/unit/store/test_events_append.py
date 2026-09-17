# tests/unit/store/test_events_append.py
import pytest
from tests.conftest import load_fixture
from where_my_job.store import db, events, applications, jobs, streams
from where_my_job.errors import InvalidInput

V1 = load_fixture("streams/custom.interviews.v1.json")
V2 = load_fixture("streams/custom.interviews.v2.json")

def _job(conn, clock, job_id="boss:SYN1"):
    with db.write_tx(conn):
        jobs.ensure(conn, clock, job_id, "boss", job_id.split(":")[1], None, None)

def _req(**kw):
    base = {"schema_version": 1, "stream": "applications", "stream_revision": 1, "type": "applied",
            "subject_kind": "application", "subject_id": None, "occurred_at": "2026-09-10T16:00:00+08:00",
            "payload": {"job_id": "boss:SYN1"}, "idempotency_key": "syn-applied-0001", "origin": "user"}
    base.update(kw); return base

def test_first_applied_creates_identity_atomically(conn, clock):
    _job(conn, clock)
    with db.write_tx(conn):
        r = events.append(conn, clock, _req())
    assert r["created"] is True and r["root_event_id"] == r["current_event_id"] and r["application_id"].startswith("app_")
    app = applications.get(conn, r["application_id"])
    assert app["job_id"] == "boss:SYN1"
    ev = conn.execute("select * from events where event_id=?", (r["root_event_id"],)).fetchone()
    assert ev["subject_id"] == r["application_id"] and ev["occurred_at"] == "2026-09-10T08:00:00.000000Z" and ev["stream_revision"] == 1
    assert events.by_idempotency_key(conn, "syn-applied-0001")["event_id"] == r["root_event_id"]

def test_applied_missing_job_rolls_back_no_identity(conn, clock):
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            events.append(conn, clock, _req(payload={"job_id": "boss:NOPE"}))
    assert ei.value.code == "SUBJECT_MISSING"
    assert conn.execute("select count(*) from applications").fetchone()[0] == 0
    assert conn.execute("select count(*) from events").fetchone()[0] == 0

def test_same_job_two_applications(conn, clock):
    _job(conn, clock)
    with db.write_tx(conn):
        a = events.append(conn, clock, _req())
        clock.advance(1)
        b = events.append(conn, clock, _req(idempotency_key="syn-applied-0002", occurred_at="2026-09-12T08:00:00Z"))
    assert a["application_id"] != b["application_id"]
    assert conn.execute("select application_id from v_job_application where job_id='boss:SYN1'").fetchone()[0] == b["application_id"]

def test_idempotent_retry_returns_original_and_conflict_on_diff(conn, clock):
    _job(conn, clock)
    with db.write_tx(conn):
        a = events.append(conn, clock, _req())
    with db.write_tx(conn):                     # 幂等重试不推进时钟
        again = events.append(conn, clock, _req())
    assert again["created"] is False and again["root_event_id"] == a["root_event_id"] and again["application_id"] == a["application_id"]
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            events.append(conn, clock, _req(payload={"job_id": "boss:SYN1", "channel": "boss"}))
    assert ei.value.code == "IDEMPOTENCY_CONFLICT"
    assert conn.execute("select count(*) from events").fetchone()[0] == 1

def test_applied_retry_with_explicit_subject_id_is_a_different_input(conn, clock):
    _job(conn, clock)
    with db.write_tx(conn):
        a = events.append(conn, clock, _req())
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            events.append(conn, clock, _req(subject_id=a["application_id"]))
    assert ei.value.code == "IDEMPOTENCY_CONFLICT"

def test_retry_binds_request_revision_after_upgrade(conn, clock):
    """升版后：同键同内容、请求仍绑定 1 → 返回原 ID；同键改绑 2 → 冲突；新键绑定非活动版本 1 → 拒绝。"""
    _job(conn, clock)
    with db.write_tx(conn):
        streams.register(conn, clock, V1)
        a = events.append(conn, clock, _req())
        clock.advance(1)
        sched = _req(stream="custom.interviews", type="scheduled", subject_id=a["application_id"],
                     payload={"round": "1", "at": "2026-09-15T02:00:00Z"}, idempotency_key="syn-sched-0001")
        s = events.append(conn, clock, sched)
        streams.register(conn, clock, V2)
    with db.write_tx(conn):
        again = events.append(conn, clock, dict(sched))
    assert again["created"] is False and again["root_event_id"] == s["root_event_id"] and again["stream_revision"] == 1
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            events.append(conn, clock, dict(sched, stream_revision=2))
    assert ei.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            events.append(conn, clock, dict(sched, idempotency_key="syn-sched-0002", payload={"round": "2", "at": "2026-09-16T02:00:00Z"}))
    assert ei.value.code == "SEMANTIC_INVALID" and ei.value.path == "$.stream_revision"

def test_replied_before_applied_rejected(conn, clock):
    _job(conn, clock)
    with db.write_tx(conn):
        a = events.append(conn, clock, _req())
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            events.append(conn, clock, _req(type="replied", subject_id=a["application_id"], payload={},
                                             occurred_at="2026-09-09T08:00:00Z", idempotency_key="syn-replied-0001"))
    assert ei.value.code == "SEMANTIC_INVALID" and ei.value.path == "$.occurred_at"

def test_subject_must_exist_for_application_and_be_given(conn, clock):
    _job(conn, clock)
    with db.write_tx(conn):
        streams.register(conn, clock, V1)
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            events.append(conn, clock, _req(stream="custom.interviews", type="scheduled", subject_id="app_404",
                                             payload={"round": "1", "at": "2026-09-15T02:00:00Z"}, idempotency_key="syn-sched-0404"))
    assert ei.value.code == "SUBJECT_MISSING"
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            events.append(conn, clock, _req(type="replied", subject_id=None, payload={}, idempotency_key="syn-replied-0404"))
    assert ei.value.path == "$.subject_id"

def test_unknown_stream_revision_and_payload_errors(conn, clock):
    _job(conn, clock)
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            events.append(conn, clock, _req(stream="custom.nope"))
    assert ei.value.code == "NOT_FOUND" and ei.value.path == "$.stream_revision"
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            events.append(conn, clock, _req(stream_revision=9))
    assert ei.value.code == "NOT_FOUND"
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            events.append(conn, clock, _req(payload={"job_id": "boss:SYN1", "bogus": 1}))
    assert ei.value.items()[0].path == "$.payload.bogus"

def test_existing_key_with_nonexistent_revision_is_conflict_not_not_found(conn, clock):
    _job(conn, clock)
    with db.write_tx(conn):
        events.append(conn, clock, _req())
    for bad in (_req(stream_revision=9), _req(stream="custom.nope")):
        with pytest.raises(InvalidInput) as ei:
            with db.write_tx(conn):
                events.append(conn, clock, bad)
        assert ei.value.code == "IDEMPOTENCY_CONFLICT" and ei.value.path == "$.idempotency_key"
    assert conn.execute("select count(*) from events").fetchone()[0] == 1
