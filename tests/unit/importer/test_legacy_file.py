import json
import pytest
from tests.conftest import FIXTURES
from where_my_job.ids import sha256_bytes
from where_my_job.importer.legacy import read_legacy_file, LegacyFileError

L = FIXTURES / "legacy"

def test_read_ok_file_yields_records_and_meta():
    lf = read_legacy_file(L / "合肥_AI产品经理.json", tz_assumption="Asia/Shanghai")
    assert lf.keyword == "AI产品经理" and lf.city == "合肥" and lf.name == "合肥_AI产品经理.json"
    assert lf.sha256 == sha256_bytes((L / "合肥_AI产品经理.json").read_bytes())
    assert lf.observed_at_utc == "2026-09-14T03:19:31.241776Z" and lf.observed_at_raw == "2026-09-14T11:19:31.241776"
    assert lf.tz_assumption == "Asia/Shanghai" and lf.source_item_count == 3
    assert len(lf.records) == 3 and lf.errors == []

def test_hash_comes_from_the_bytes_that_were_parsed(tmp_path):
    p = tmp_path / "合肥_AI产品经理.json"
    original = (L / "合肥_AI产品经理.json").read_bytes()
    p.write_bytes(original)
    lf = read_legacy_file(p, tz_assumption="Asia/Shanghai")
    p.write_text('{"jobs": []}')
    assert lf.sha256 == sha256_bytes(original) and len(lf.records) == 3

@pytest.mark.parametrize("content", ['{"jobs": [', '{"scraped_at": "2026-09-14T11:00:00", "jobs": [{"x": NaN}]}', '[1]'])
def test_unreadable_files_raise(tmp_path, content):
    p = tmp_path / "x_y.json"; p.write_text(content)
    with pytest.raises(LegacyFileError):
        read_legacy_file(p, tz_assumption="Asia/Shanghai")

def test_bad_record_goes_to_errors_not_exception(tmp_path):
    p = tmp_path / "x_y.json"
    p.write_text(json.dumps({"keyword": "y", "city": "x", "scraped_at": "2026-09-14T11:00:00",
                             "jobs": [{"title": "no id"}, {"encrypt_job_id": "SYN9", "tags": ["bad"]}]}), encoding="utf-8")
    lf = read_legacy_file(p, tz_assumption="Asia/Shanghai")
    assert lf.records == [] and [e["item_index"] for e in lf.errors] == [0, 1]
    assert "encrypt_job_id" in lf.errors[0]["message"] and lf.source_item_count == 2

def test_missing_or_offset_scraped_at(tmp_path):
    p = tmp_path / "a_b.json"
    p.write_text(json.dumps({"jobs": []}))
    lf = read_legacy_file(p, tz_assumption="Asia/Shanghai")
    assert lf.observed_at_utc is None and lf.observed_at_raw is None and lf.tz_assumption is None
    p.write_text(json.dumps({"scraped_at": "2026-09-14T11:00:00+08:00", "jobs": []}))
    lf = read_legacy_file(p, tz_assumption="Asia/Shanghai")
    assert lf.observed_at_utc == "2026-09-14T03:00:00.000000Z" and lf.tz_assumption is None
