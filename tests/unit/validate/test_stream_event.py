# tests/unit/validate/test_stream_event.py
from tests.conftest import load_fixture
from where_my_job.validate import validate, Facts
from where_my_job.validate.semantic import event as event_semantic
from where_my_job.streams.builtin import APPLICATIONS_DEFINITION

V1 = load_fixture("streams/custom.interviews.v1.json")
V2 = load_fixture("streams/custom.interviews.v2.json")
FACTS = Facts(job_ids=frozenset({"boss:SYN0001aaaa"}),
              active_streams={"applications": APPLICATIONS_DEFINITION, "custom.interviews": V1},
              application_ids_by_job={"boss:SYN0001aaaa": frozenset({"app_1"})})

def test_stream_ok():
    assert validate("stream", V1) == []

def test_stream_projection_unsupported():
    issues = validate("stream", load_fixture("streams/custom.bad-projection.json"))
    assert issues[0].code == "UNSUPPORTED_SETTING" and issues[0].path == "$.projection"

def test_stream_bad_names_and_corrected():
    d = {**V1, "stream": "custom.Bad", "types": {"corrected": {"required": [], "fields": {}}, "ok": {"required": ["x"], "fields": {}}}}
    paths = {i.path for i in validate("stream", d)}
    assert {"$.stream", "$.types.corrected", "$.types.ok.required"} <= paths

def _ev(**kw):
    base = {"schema_version": 1, "stream": "applications", "stream_revision": 1, "type": "applied",
            "subject_kind": "application", "occurred_at": "2026-09-10T08:00:00Z",
            "payload": {"job_id": "boss:SYN0001aaaa"}, "idempotency_key": "syn-applied-0001", "origin": "user"}
    base.update(kw); return base

def test_event_schema_requires_stream_revision():
    ev = _ev(); del ev["stream_revision"]
    issues = validate("event", ev, FACTS)
    assert issues and issues[0].code == "SCHEMA_INVALID" and any("stream_revision" in i.message for i in issues)

def test_idempotency_key_min_length_8():
    issues = validate("event", _ev(idempotency_key="k2"), FACTS)
    assert issues[0].code == "SCHEMA_INVALID" and issues[0].path == "$.idempotency_key"

def test_event_applied_ok_and_missing_job():
    assert validate("event", _ev(), FACTS) == []
    issues = validate("event", _ev(payload={"job_id": "boss:NOPE"}), FACTS)
    assert issues[0].code == "SUBJECT_MISSING" and issues[0].path == "$.payload.job_id"

def test_event_applied_must_not_carry_subject_id():
    issues = validate("event", _ev(subject_id="app_1"), FACTS)
    assert issues[0].path == "$.subject_id"

def test_event_non_applied_requires_existing_application():
    assert validate("event", _ev(type="replied", subject_id="app_1", payload={}, idempotency_key="syn-replied-0002"), FACTS) == []
    issues = validate("event", _ev(type="replied", subject_id="app_404", payload={}, idempotency_key="syn-replied-0003"), FACTS)
    assert issues[0].code == "SUBJECT_MISSING"

def test_event_custom_stream_payload_types():
    ok = _ev(stream="custom.interviews", type="scheduled", subject_id="app_1",
             payload={"round": "1", "at": "2026-09-15T02:00:00Z"}, idempotency_key="syn-sched-0004")
    assert validate("event", ok, FACTS) == []
    bad = _ev(stream="custom.interviews", type="scheduled", subject_id="app_1", payload={"round": 1}, idempotency_key="syn-sched-0005")
    paths = {i.path for i in validate("event", bad, FACTS)}
    assert {"$.payload.round", "$.payload.at"} <= paths

def test_event_unknown_stream_and_type():
    assert validate("event", _ev(stream="custom.nope", subject_id="app_1", idempotency_key="syn-nope-0006"), FACTS)[0].path == "$.stream"
    assert validate("event", _ev(type="ghosted", subject_id="app_1", idempotency_key="syn-ghost-0007"), FACTS)[0].path == "$.type"

def test_new_event_must_bind_active_revision_unless_definition_given():
    facts = Facts(job_ids=FACTS.job_ids, application_ids_by_job=FACTS.application_ids_by_job,
                  active_streams={**FACTS.active_streams, "custom.interviews": V2})
    old = _ev(stream="custom.interviews", stream_revision=1, type="scheduled", subject_id="app_1",
              payload={"round": "1", "at": "2026-09-15T02:00:00Z"}, idempotency_key="syn-sched-0009")
    issues = validate("event", old, facts)
    assert issues[0].code == "SEMANTIC_INVALID" and issues[0].path == "$.stream_revision"
    # 调用方已按请求版本解析出定义（历史重试、纠错）时，按给定定义检查，不再要求活动版本
    assert event_semantic.check(old, facts, definition=V1) == []

def test_time_fields_parse_failures_are_schema_invalid_with_paths():
    issues = validate("event", _ev(occurred_at="2026-02-30T08:00:00Z"), FACTS)
    assert issues[0].code == "SCHEMA_INVALID" and issues[0].path == "$.occurred_at"
    issues = validate("event", _ev(occurred_at="2026-09-10T08:00:00.000000"), FACTS)
    assert issues[0].code == "SCHEMA_INVALID" and issues[0].path == "$.occurred_at"
    bad_payload_time = _ev(stream="custom.interviews", type="scheduled", subject_id="app_1",
                           payload={"round": "1", "at": "2026-13-01T00:00:00Z"}, idempotency_key="syn-sched-0010")
    issues = validate("event", bad_payload_time, FACTS)
    assert [(i.code, i.path) for i in issues] == [("SCHEMA_INVALID", "$.payload.at")]
    c = _ev(type="corrected", subject_id="app_1", payload={}, idempotency_key="syn-corr-0011",
            corrected={"corrected_event_id": "evt_x", "op": "replace", "original_type": "applied",
                       "replacement_payload": {"job_id": "boss:SYN0001aaaa"}, "replacement_occurred_at": "yesterday"})
    issues = validate("event", c, FACTS)
    assert ("SCHEMA_INVALID", "$.corrected.replacement_occurred_at") in [(i.code, i.path) for i in issues]
    assert event_semantic.time_issues(c)[0].path == "$.corrected.replacement_occurred_at"

def test_event_corrected_block_shape():
    c = _ev(type="corrected", subject_id="app_1", payload={}, idempotency_key="syn-corr-0008",
            corrected={"corrected_event_id": "evt_x", "op": "replace", "original_type": "applied",
                       "replacement_payload": {"job_id": "boss:SYN0001aaaa", "channel": "boss"},
                       "replacement_occurred_at": "2026-09-10T09:00:00Z"})
    assert validate("event", c, FACTS) == []
    bad = dict(c); bad["corrected"] = {"corrected_event_id": "evt_x", "op": "retract", "original_type": "applied"}
    assert any(i.path == "$.corrected.original_type" for i in validate("event", bad, FACTS))
    missing = _ev(type="corrected", subject_id="app_1", payload={}, idempotency_key="syn-corr-0009")
    assert validate("event", missing, FACTS)[0].path == "$.corrected"

def test_event_subject_kind_none_rules():
    d = {**V1, "stream": "custom.diary", "subject_kind": "none", "types": {"wrote": {"required": [], "fields": {"text": "string"}}}}
    facts = Facts(active_streams={"custom.diary": d})
    assert validate("event", _ev(stream="custom.diary", type="wrote", subject_kind="none", payload={"text": "x"},
                                 idempotency_key="syn-diary-0010"), facts) == []
    issues = validate("event", _ev(stream="custom.diary", type="wrote", subject_kind="none", subject_id="j", payload={},
                                   idempotency_key="syn-diary-0011"), facts)
    assert any(i.path == "$.subject_id" for i in issues)
