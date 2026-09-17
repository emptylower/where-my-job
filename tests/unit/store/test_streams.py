# tests/unit/store/test_streams.py
import pytest
from tests.conftest import load_fixture
from where_my_job.store import db, streams
from where_my_job.errors import InvalidInput

V1 = load_fixture("streams/custom.interviews.v1.json")
V2 = load_fixture("streams/custom.interviews.v2.json")
BAD = load_fixture("streams/custom.interviews.v2-incompatible.json")

def test_register_first_revision_activates(conn, clock):
    with db.write_tx(conn):
        r = streams.register(conn, clock, V1)
    assert r == {"stream": "custom.interviews", "stream_revision": 1, "content_hash": r["content_hash"], "created": True}
    assert streams.get_active(conn, "custom.interviews")["stream_revision"] == 1
    assert streams.get_definition(conn, "custom.interviews", 1)["types"]["scheduled"]["required"] == ["round", "at"]

def test_register_same_content_is_noop_same_revision_diff_content_rejected(conn, clock):
    with db.write_tx(conn):
        streams.register(conn, clock, V1)
    with db.write_tx(conn):
        r = streams.register(conn, clock, dict(V1))
    assert r["created"] is False and r["stream_revision"] == 1
    changed = {**V1, "types": {**V1["types"], "extra": {"required": [], "fields": {}}}}
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            streams.register(conn, clock, changed)
    assert ei.value.code == "INCOMPATIBLE_REVISION"

def test_register_compatible_upgrade_switches_active_and_keeps_old(conn, clock):
    with db.write_tx(conn):
        streams.register(conn, clock, V1)
    with db.write_tx(conn):
        r = streams.register(conn, clock, V2)
    assert r["stream_revision"] == 2 and streams.get_active(conn, "custom.interviews")["stream_revision"] == 2
    assert [x["stream_revision"] for x in streams.list_revisions(conn, "custom.interviews")] == [1, 2]
    assert streams.get_definition(conn, "custom.interviews", 1)["types"].keys() == {"scheduled", "done"}

def test_register_incompatible_rejected_and_active_unchanged(conn, clock):
    with db.write_tx(conn):
        streams.register(conn, clock, V1)
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            streams.register(conn, clock, BAD)
    assert ei.value.code == "INCOMPATIBLE_REVISION" and ei.value.items()[0].path == "$.types"
    assert streams.get_active(conn, "custom.interviews")["stream_revision"] == 1
    assert conn.execute("select count(*) from stream_registry where stream='custom.interviews'").fetchone()[0] == 1

def test_register_skipping_revision_rejected(conn, clock):
    with db.write_tx(conn):
        streams.register(conn, clock, V1)
    with pytest.raises(InvalidInput):
        with db.write_tx(conn):
            streams.register(conn, clock, {**V2, "stream_revision": 3})

def test_first_revision_must_be_1(conn, clock):
    with pytest.raises(InvalidInput):
        with db.write_tx(conn):
            streams.register(conn, clock, {**V1, "stream_revision": 2})

def test_builtin_cannot_be_reregistered(conn, clock):
    from where_my_job.streams.builtin import APPLICATIONS_DEFINITION
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            streams.register(conn, clock, APPLICATIONS_DEFINITION)
    assert ei.value.code == "RESERVED_KEY"

def test_list_all_includes_builtin(conn):
    names = {s["stream"] for s in streams.list_all(conn)}
    assert "applications" in names
