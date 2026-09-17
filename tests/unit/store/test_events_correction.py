# tests/unit/store/test_events_correction.py
import json, sqlite3, pytest
from tests.conftest import load_fixture
from where_my_job.store import db, events, streams, jobs
from where_my_job.errors import InvalidInput

def _req(**kw):
    base = {"schema_version": 1, "stream": "applications", "stream_revision": 1, "type": "applied",
            "subject_kind": "application", "subject_id": None, "occurred_at": "2026-09-10T08:00:00Z",
            "payload": {"job_id": "boss:SYN1"}, "idempotency_key": "syn-applied-0001", "origin": "user"}
    base.update(kw); return base

def _append(conn, clock, req):
    clock.advance(1)                    # 只在插入新的语义事件前推进时钟
    return events.append(conn, clock, req)

def _setup(conn, clock):
    with db.write_tx(conn):
        jobs.ensure(conn, clock, "boss:SYN1", "boss", "SYN1", None, None)
        jobs.ensure(conn, clock, "boss:SYN2", "boss", "SYN2", None, None)
        streams.register(conn, clock, load_fixture("streams/custom.interviews.v1.json"))
        a = _append(conn, clock, _req())
        r = _append(conn, clock, _req(type="replied", subject_id=a["application_id"], payload={},
                                      occurred_at="2026-09-11T08:00:00Z", idempotency_key="syn-replied-0001"))
    return a, r

def _corr(target, op, app_id, key, occurred_at="2026-09-14T08:00:00Z", **kw):
    c = {"corrected_event_id": target, "op": op}
    c.update(kw)
    return _req(type="corrected", subject_id=app_id, payload={}, idempotency_key=key, occurred_at=occurred_at, corrected=c)

def _count_corrections(conn):
    return conn.execute("select count(*) from events where type='corrected'").fetchone()[0]

def test_replace_applied_time_and_payload_keeps_own_record_time(conn, clock):
    a, r = _setup(conn, clock)
    with db.write_tx(conn):
        c = _append(conn, clock, _corr(a["root_event_id"], "replace", a["application_id"], "syn-corr-0001",
                                       original_type="applied", replacement_payload={"job_id": "boss:SYN1", "channel": "boss"},
                                       replacement_occurred_at="2026-09-10T09:00:00Z"))
    assert c["root_event_id"] == a["root_event_id"] and c["current_event_id"] == c["event_id"]
    stored = conn.execute("select occurred_at, payload_json from events where event_id=?", (c["event_id"],)).fetchone()
    assert stored["occurred_at"] == "2026-09-14T08:00:00.000000Z"                          # 纠错记录自己的发生时间
    assert json.loads(stored["payload_json"])["replacement_occurred_at"] == "2026-09-10T09:00:00.000000Z"
    eff = conn.execute("select occurred_at, payload_json, corrected from v_effective_events where root_id=?", (a["root_event_id"],)).fetchone()
    assert eff["occurred_at"] == "2026-09-10T09:00:00.000000Z" and json.loads(eff["payload_json"])["channel"] == "boss" and eff["corrected"] == 1

def test_correction_retry_with_time_different_from_root_is_idempotent(conn, clock):
    a, r = _setup(conn, clock)
    req = _corr(r["root_event_id"], "retract", a["application_id"], "syn-corr-retry", occurred_at="2026-09-14T16:00:00+08:00")
    with db.write_tx(conn):
        first = _append(conn, clock, req)
    with db.write_tx(conn):
        again = events.append(conn, clock, dict(req))
    assert again["created"] is False and again["event_id"] == first["event_id"] and _count_corrections(conn) == 1

def test_correction_must_target_tail(conn, clock):
    a, r = _setup(conn, clock)
    with db.write_tx(conn):
        c1 = _append(conn, clock, _corr(r["root_event_id"], "replace", a["application_id"], "syn-corr-0101",
                                        original_type="replied", replacement_payload={"note": "hr"}, replacement_occurred_at="2026-09-11T09:00:00Z"))
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            _append(conn, clock, _corr(r["root_event_id"], "retract", a["application_id"], "syn-corr-0102"))
    assert ei.value.code == "CORRECTION_NOT_TAIL"
    with db.write_tx(conn):   # 引用新末端才行
        c2 = _append(conn, clock, _corr(c1["event_id"], "retract", a["application_id"], "syn-corr-0102"))
    assert c2["root_event_id"] == r["root_event_id"]
    assert conn.execute("select count(*) from v_effective_events where root_id=?", (r["root_event_id"],)).fetchone()[0] == 0

def test_cross_stream_and_cross_subject_rejected(conn, clock):
    a, r = _setup(conn, clock)
    with db.write_tx(conn):
        b2 = _append(conn, clock, _req(idempotency_key="syn-applied-0002", payload={"job_id": "boss:SYN2"}))
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            _append(conn, clock, _corr(r["root_event_id"], "retract", b2["application_id"], "syn-cross-0001"))
    assert ei.value.code == "CORRECTION_CROSS_STREAM"
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            _append(conn, clock, _req(stream="custom.interviews", type="corrected", subject_id=a["application_id"], payload={},
                                      idempotency_key="syn-cross-0002", corrected={"corrected_event_id": r["root_event_id"], "op": "retract"}))
    assert ei.value.code == "CORRECTION_CROSS_STREAM"

def test_replace_cannot_change_type_or_job(conn, clock):
    a, r = _setup(conn, clock)
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            _append(conn, clock, _corr(r["root_event_id"], "replace", a["application_id"], "syn-type-0001",
                                       original_type="interview", replacement_payload={}, replacement_occurred_at="2026-09-11T09:00:00Z"))
    assert ei.value.items()[0].path == "$.corrected.original_type"
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            _append(conn, clock, _corr(a["root_event_id"], "replace", a["application_id"], "syn-type-0002",
                                       original_type="applied", replacement_payload={"job_id": "boss:SYN2"}, replacement_occurred_at="2026-09-10T08:00:00Z"))
    assert ei.value.items()[0].path == "$.corrected.replacement_payload.job_id"

def test_retract_applied_with_dependents_rejected_then_ok(conn, clock):
    a, r = _setup(conn, clock)
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            _append(conn, clock, _corr(a["root_event_id"], "retract", a["application_id"], "syn-dep-0001"))
    assert ei.value.code == "DEPENDENT_EVENTS"
    with db.write_tx(conn):
        _append(conn, clock, _corr(r["root_event_id"], "retract", a["application_id"], "syn-dep-0002"))
        _append(conn, clock, _corr(a["root_event_id"], "retract", a["application_id"], "syn-dep-0003"))
    assert conn.execute("select count(*) from v_job_application").fetchone()[0] == 0

def test_restoring_dependent_after_applied_retracted_is_rejected_then_allowed_in_order(conn, clock):
    """撤回后续 → 撤回 applied → 恢复后续：失败且不多一条历史；先恢复 applied 再恢复后续：成功。"""
    a, r = _setup(conn, clock)
    with db.write_tx(conn):
        c_r = _append(conn, clock, _corr(r["root_event_id"], "retract", a["application_id"], "syn-orphan-0001"))
        c_a = _append(conn, clock, _corr(a["root_event_id"], "retract", a["application_id"], "syn-orphan-0002"))
    before = _count_corrections(conn)
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            _append(conn, clock, _corr(c_r["event_id"], "replace", a["application_id"], "syn-orphan-0003",
                                       original_type="replied", replacement_payload={"note": "back"},
                                       replacement_occurred_at="2026-09-11T10:00:00Z"))
    assert ei.value.code == "DEPENDENT_EVENTS" and _count_corrections(conn) == before
    with db.write_tx(conn):
        _append(conn, clock, _corr(c_a["event_id"], "replace", a["application_id"], "syn-orphan-0004",
                                   original_type="applied", replacement_payload={"job_id": "boss:SYN1"},
                                   replacement_occurred_at="2026-09-10T08:00:00Z"))
        _append(conn, clock, _corr(c_r["event_id"], "replace", a["application_id"], "syn-orphan-0003",
                                   original_type="replied", replacement_payload={"note": "back"},
                                   replacement_occurred_at="2026-09-11T10:00:00Z"))
    assert tuple(conn.execute("select application_id, application_state from v_job_application where job_id='boss:SYN1'").fetchone()) == (a["application_id"], "replied")

def test_custom_stream_events_are_dependents(conn, clock):
    a, r = _setup(conn, clock)
    with db.write_tx(conn):
        _append(conn, clock, _corr(r["root_event_id"], "retract", a["application_id"], "syn-cust-0000"))
        _append(conn, clock, _req(stream="custom.interviews", type="scheduled", subject_id=a["application_id"],
                                  payload={"round": "1", "at": "2026-09-15T02:00:00Z"}, occurred_at="2026-09-12T08:00:00Z", idempotency_key="syn-cust-0001"))
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            _append(conn, clock, _corr(a["root_event_id"], "retract", a["application_id"], "syn-cust-0002"))
    assert ei.value.code == "DEPENDENT_EVENTS"

def test_replace_that_breaks_business_time_rejected(conn, clock):
    a, r = _setup(conn, clock)
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):   # 把 applied 挪到 replied 之后
            _append(conn, clock, _corr(a["root_event_id"], "replace", a["application_id"], "syn-time-0001",
                                       original_type="applied", replacement_payload={"job_id": "boss:SYN1"}, replacement_occurred_at="2026-09-12T08:00:00Z"))
    assert ei.value.code == "SEMANTIC_INVALID" and ei.value.path == "$.corrected.replacement_occurred_at"
    assert _count_corrections(conn) == 0

def test_replace_a_retracted_fact_revives_it(conn, clock):
    a, r = _setup(conn, clock)
    with db.write_tx(conn):
        c1 = _append(conn, clock, _corr(r["root_event_id"], "retract", a["application_id"], "syn-revive-0001"))
        _append(conn, clock, _corr(c1["event_id"], "replace", a["application_id"], "syn-revive-0002",
                                   original_type="replied", replacement_payload={"note": "revived"}, replacement_occurred_at="2026-09-11T10:00:00Z"))
    eff = conn.execute("select payload_json from v_effective_events where root_id=?", (r["root_event_id"],)).fetchone()
    assert json.loads(eff[0]) == {"note": "revived"}

def test_fork_detected(conn, clock):
    """绕过末端检查直接插入第二条指向同一目标的纠错：唯一索引失败 → CORRECTION_FORK。"""
    a, r = _setup(conn, clock)
    with db.write_tx(conn):
        _append(conn, clock, _corr(r["root_event_id"], "retract", a["application_id"], "syn-fork-0001"))
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            try:
                conn.execute("""insert into events(event_id,stream,stream_revision,type,subject_kind,subject_id,occurred_at,recorded_at,payload_json,idempotency_key,corrected_event_id,origin)
                                values ('evt_fork','applications',1,'corrected','application',?, '2026-09-11T08:00:00.000000Z','t','{"op":"retract"}','syn-fork-0002',?, 'user')""",
                             (a["application_id"], r["root_event_id"]))
            except sqlite3.IntegrityError as e:
                raise events.fork_error(e)
    assert ei.value.code == "CORRECTION_FORK"
