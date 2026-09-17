# tests/unit/streams/test_builtin.py
import pytest
from where_my_job.streams import builtin as b

def test_applications_definition_shape():
    d = b.APPLICATIONS_DEFINITION
    assert d["stream"] == "applications" and d["stream_revision"] == 1 and d["subject_kind"] == "application"
    assert set(d["types"]) == {"applied", "replied", "interview", "offer", "rejected", "withdrawn"}
    assert d["types"]["applied"]["required"] == ["job_id"]
    assert b.definition_hash(d) == b.definition_hash(dict(d))  # 稳定

def test_check_payload_types_and_required():
    d = {"schema_version": 1, "stream": "custom.x", "stream_revision": 1, "subject_kind": "job",
         "types": {"t": {"required": ["round", "at"],
                          "fields": {"round": "string", "at": "datetime", "n": "integer", "f": "number",
                                     "ok": "boolean", "k": {"enum": ["a", "b"]}}}}}
    assert b.check_payload(d, "t", {"round": "1", "at": "2026-09-14T00:00:00Z"}) == []
    errs = b.check_payload(d, "t", {"round": 1, "n": True, "f": "1", "ok": 1, "k": "c", "zzz": 1})
    paths = {e[0] for e in errs}
    assert paths == {"$.payload.round", "$.payload.at", "$.payload.n", "$.payload.f", "$.payload.ok", "$.payload.k", "$.payload.zzz"}

def test_datetime_failures_use_shared_message():
    d = {"schema_version": 1, "stream": "custom.x", "stream_revision": 1, "subject_kind": "job",
         "types": {"t": {"required": [], "fields": {"at": "datetime"}}}}
    assert b.check_payload(d, "t", {"at": "2026-02-30T00:00:00Z"}) == [("$.payload.at", b.DATETIME_MSG)]
    assert ("$.corrected.replacement_occurred_at", b.DATETIME_MSG) in b.check_corrected_block(
        {"corrected_event_id": "evt_x", "op": "replace", "original_type": "t", "replacement_payload": {}, "replacement_occurred_at": "nope"})

def test_check_payload_unknown_type_name():
    d = b.APPLICATIONS_DEFINITION
    assert b.check_payload(d, "nope", {})[0][0] == "$.type"
    assert b.check_payload(d, "corrected", {})[0][0] == "$.type"

def test_compatible_upgrade_rules():
    old = {"schema_version": 1, "stream": "custom.i", "stream_revision": 1, "subject_kind": "application",
           "types": {"scheduled": {"required": ["round"], "fields": {"round": "string", "at": "datetime"}}}}
    ok = {**old, "stream_revision": 2,
          "types": {"scheduled": {"required": ["round"], "fields": {"round": "string", "at": "datetime", "format": "string"}},
                    "done": {"required": [], "fields": {"round": "string"}}}}
    assert b.compatibility_problems(old, ok) == []
    bad_required = {**ok, "types": {**ok["types"], "scheduled": {"required": ["round", "at"], "fields": ok["types"]["scheduled"]["fields"]}}}
    assert any("required" in p for p in b.compatibility_problems(old, bad_required))
    bad_type = {**ok, "types": {**ok["types"], "scheduled": {"required": ["round"], "fields": {"round": "integer", "at": "datetime"}}}}
    assert any("round" in p for p in b.compatibility_problems(old, bad_type))
    bad_subject = {**ok, "subject_kind": "job"}
    assert any("subject_kind" in p for p in b.compatibility_problems(old, bad_subject))
    removed = {**ok, "types": {"done": ok["types"]["done"]}}
    assert any("scheduled" in p for p in b.compatibility_problems(old, removed))
    bad_rev = {**ok, "stream_revision": 3}
    assert any("stream_revision" in p for p in b.compatibility_problems(old, bad_rev))

def test_identifier_rules():
    assert b.is_identifier("round_1") and not b.is_identifier("Round") and not b.is_identifier("1a") and not b.is_identifier("")
