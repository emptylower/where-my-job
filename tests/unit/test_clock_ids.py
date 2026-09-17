from datetime import datetime, timezone
import pytest
from where_my_job.clock import FixedClock, iso_utc, parse_iso
from where_my_job.ids import new_id, sha256_json, canonical_json

def test_iso_roundtrip_and_naive_rejected():
    dt = datetime(2026, 9, 14, 3, 19, 31, 241776, tzinfo=timezone.utc)
    assert iso_utc(dt) == "2026-09-14T03:19:31.241776Z"
    assert parse_iso("2026-09-14T11:19:31.241776+08:00") == dt
    with pytest.raises(ValueError):
        parse_iso("2026-09-14T11:19:31")
    with pytest.raises(ValueError):
        parse_iso(20260914)

def test_fixed_clock_advance():
    c = FixedClock(datetime(2026, 9, 14, tzinfo=timezone.utc))
    m0 = c.monotonic()
    c.advance(12)
    assert c.monotonic() - m0 == 12 and c.now().second == 12

def test_new_id_shape_and_injectable():
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    i = new_id("run", now, rand=b"\x00" * 8)
    assert i.startswith("run_") and i.endswith("0" * 16) and len(i) == 4 + 13 + 16

def test_canonical_json_is_sorted_hash_stable_and_rejects_nan():
    assert canonical_json({"b": 1, "a": "中"}) == '{"a":"中","b":1}'
    assert sha256_json({"b": 1, "a": 1}) == sha256_json({"a": 1, "b": 1})
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
