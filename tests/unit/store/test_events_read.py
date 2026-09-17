# tests/unit/store/test_events_read.py
import json, pytest
from tests.conftest import load_fixture
from where_my_job.clock import iso_utc
from where_my_job.ids import canonical_json
from where_my_job.errors import InvalidInput
from where_my_job.store import db, events, streams, jobs

DIARY = {"schema_version": 1, "stream": "custom.diary", "stream_revision": 1, "subject_kind": "none",
         "types": {"wrote": {"required": ["text"], "fields": {"text": "string"}}}}

def _req(**kw):
    base = {"schema_version": 1, "stream": "applications", "stream_revision": 1, "type": "applied",
            "subject_kind": "application", "subject_id": None, "occurred_at": "2026-09-10T08:00:00Z",
            "payload": {"job_id": "boss:SYN1"}, "idempotency_key": "syn-applied-0001", "origin": "user"}
    base.update(kw); return base

def _new(conn, clock, req):
    clock.advance(1)
    return events.append(conn, clock, req)

def _seed(conn, clock):
    with db.write_tx(conn):
        jobs.ensure(conn, clock, "boss:SYN1", "boss", "SYN1", None, None)
        streams.register(conn, clock, load_fixture("streams/custom.interviews.v1.json"))
        a = _new(conn, clock, _req())
        app = a["application_id"]
        _new(conn, clock, _req(stream="custom.interviews", type="scheduled", subject_id=app, occurred_at="2026-09-12T08:00:00Z",
                               payload={"round": "1", "at": "2026-09-15T02:00:00Z"}, idempotency_key="syn-sched-0001"))
        _new(conn, clock, _req(stream="custom.interviews", type="done", subject_id=app, occurred_at="2026-09-15T04:00:00Z",
                               payload={"round": "1", "self_rating": 4}, idempotency_key="syn-done-0001"))
        streams.register(conn, clock, load_fixture("streams/custom.interviews.v2.json"))
        _new(conn, clock, _req(stream="custom.interviews", stream_revision=2, type="cancelled", subject_id=app,
                               occurred_at="2026-09-16T04:00:00Z", payload={"round": "2", "reason": "company"},
                               idempotency_key="syn-cancel-0001"))
    return app

def test_timeline_effective_sorted_with_declared_fields(conn, clock):
    app = _seed(conn, clock)
    page = events.timeline_page(conn, "custom.interviews", subject_id=app)
    assert (page["total"], page["limit"], page["offset"], page["truncated"]) == (3, 1000, 0, False)
    s, d, c = page["items"]
    assert [e["type"] for e in page["items"]] == ["scheduled", "done", "cancelled"]
    assert s["stream_revision"] == 1 and c["stream_revision"] == 2
    assert s["fields"]["round"] == {"present": True, "value": "1"} and s["fields"]["format"] == {"present": False, "value": None}
    assert "interviewer_title" not in s["fields"]              # 旧事件按旧声明读取
    assert c["fields"]["reason"] == {"present": True, "value": "company"}
    assert d["fields"]["questions"]["present"] is False and d["fields"]["self_rating"]["value"] == 4
    assert set(s) >= {"root_event_id", "current_event_id", "occurred_at", "recorded_at", "corrected", "origin", "subject_kind", "subject_id"}

def test_timeline_scheduled_and_done_both_kept(conn, clock):
    app = _seed(conn, clock)
    items = events.timeline_page(conn, "custom.interviews", subject_id=app)["items"]
    assert sum(1 for e in items if e["fields"]["round"]["value"] == "1") == 2

def test_timeline_truncation_metadata_and_limit_validation(conn, clock):
    app = _seed(conn, clock)
    page = events.timeline_page(conn, "custom.interviews", subject_id=app, limit=2)
    assert len(page["items"]) == 2 and page["total"] == 3 and page["truncated"] is True
    rest = events.timeline_page(conn, "custom.interviews", subject_id=app, limit=2, offset=2)
    assert len(rest["items"]) == 1 and rest["truncated"] is False
    for bad in ({"limit": 0}, {"limit": 1001}, {"offset": -1}, {"limit": True}):
        with pytest.raises(InvalidInput) as ei:
            events.timeline_page(conn, "custom.interviews", **bad)
        assert ei.value.code == "SEMANTIC_INVALID" and ei.value.path in ("$.limit", "$.offset")

def test_unknown_stream_not_found_empty_registered_stream_zero(conn, clock):
    _seed(conn, clock)
    with pytest.raises(InvalidInput) as ei:
        events.timeline_page(conn, "custom.nope")
    assert ei.value.code == "NOT_FOUND"
    with db.write_tx(conn):
        streams.register(conn, clock, DIARY)
    empty = events.timeline_page(conn, "custom.diary")
    assert (empty["items"], empty["total"], empty["truncated"]) == ([], 0, False)
    assert events.timeline_page(conn, "applications")["total"] == 1

def test_stream_history_includes_corrections(conn, clock):
    app = _seed(conn, clock)
    first = events.timeline_page(conn, "custom.interviews", subject_id=app)["items"][0]
    with db.write_tx(conn):
        _new(conn, clock, _req(stream="custom.interviews", type="corrected", subject_id=app, payload={}, idempotency_key="syn-retract-0001",
                               occurred_at="2026-09-14T08:00:00Z", corrected={"corrected_event_id": first["root_event_id"], "op": "retract"}))
    assert [e["type"] for e in events.timeline_page(conn, "custom.interviews", subject_id=app)["items"]] == ["done", "cancelled"]
    hist = events.stream_history_page(conn, "custom.interviews", subject_id=app)
    items = hist["items"]
    assert hist["total"] == 4 and items[-1]["type"] == "corrected" and items[-1]["corrected_event_id"] == first["root_event_id"]
    assert items[-1]["op"] == "retract" and any(h["superseded_by"] == items[-1]["event_id"] for h in items)

def test_stream_history_paging_is_continuous(conn, clock):
    app = _seed(conn, clock)
    full = events.stream_history_page(conn, "custom.interviews", subject_id=app)
    ids = [h["event_id"] for h in full["items"]]
    got, flags = [], []
    for offset in range(0, full["total"], 2):
        p = events.stream_history_page(conn, "custom.interviews", subject_id=app, limit=2, offset=offset)
        got += [h["event_id"] for h in p["items"]]; flags.append(p["truncated"])
    assert got == ids and len(set(got)) == len(got) and flags[-1] is False and all(flags[:-1])
    with pytest.raises(InvalidInput):
        events.stream_history_page(conn, "custom.interviews", limit=2001)

def test_same_timestamp_tie_break_follows_protocol_not_insert_order(conn, clock):
    with db.write_tx(conn):
        streams.register(conn, clock, DIARY)
        a = events.append(conn, clock, _req(stream="custom.diary", type="wrote", subject_kind="none", occurred_at="2026-09-12T00:00:00Z",
                                            payload={"text": "甲"}, idempotency_key="syn-tie-0001"))
        b2 = events.append(conn, clock, _req(stream="custom.diary", type="wrote", subject_kind="none", occurred_at="2026-09-12T00:00:00Z",
                                             payload={"text": "乙"}, idempotency_key="syn-tie-0002"))   # 不推进时钟：recorded_at 相同
    expected = sorted([a["root_event_id"], b2["root_event_id"]])
    assert [e["root_event_id"] for e in events.timeline_page(conn, "custom.diary")["items"]] == expected
    assert [h["event_id"] for h in events.stream_history_page(conn, "custom.diary")["items"]] == expected

def test_long_correction_chain_reads_true_tail_and_full_history(conn, clock):
    with db.write_tx(conn):
        streams.register(conn, clock, DIARY)
        root = _new(conn, clock, _req(stream="custom.diary", type="wrote", subject_kind="none", payload={"text": "v0"},
                                      idempotency_key="syn-diary-root"))
    n = 1200                                        # 超过旧读侧上限 1000
    now = iso_utc(clock.now())
    rows, prev = [], root["root_event_id"]
    for i in range(1, n + 1):
        eid = f"evt_chain_{i:05d}"
        payload = canonical_json({"op": "replace", "original_type": "wrote", "replacement_payload": {"text": f"v{i}"},
                                  "replacement_occurred_at": "2026-09-10T08:00:00.000000Z"})
        rows.append((eid, "custom.diary", 1, "corrected", "none", None, now, now, payload, f"syn-chain-{i:05d}", prev, "user"))
        prev = eid
    with db.write_tx(conn):
        conn.executemany("""insert into events(event_id,stream,stream_revision,type,subject_kind,subject_id,occurred_at,recorded_at,
                            payload_json,idempotency_key,corrected_event_id,origin) values (?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    eff = conn.execute("select current_id, chain_depth, payload_json from v_effective_events where root_id=?", (root["root_event_id"],)).fetchone()
    assert eff["current_id"] == prev and eff["chain_depth"] == n and json.loads(eff["payload_json"]) == {"text": f"v{n}"}
    page = events.timeline_page(conn, "custom.diary")
    assert page["total"] == 1 and page["items"][0]["current_event_id"] == prev
    hist = events.history_page(conn, prev)             # 从末端进入也回到根
    assert hist["root_event_id"] == root["root_event_id"] and hist["total"] == n + 1 and hist["truncated"] is False
    assert hist["items"][0]["event_id"] == root["root_event_id"] and hist["items"][-1]["event_id"] == prev
    assert [h["chain_depth"] for h in hist["items"][:3]] == [0, 1, 2]
    assert events.tail_of(conn, root["root_event_id"])["event_id"] == prev
    with pytest.raises(InvalidInput) as ei:
        events.history_page(conn, "evt_missing")
    assert ei.value.code == "NOT_FOUND"
