# tests/unit/store/test_bundles.py
import json
import pytest
from tests.conftest import load_fixture
from tests.helpers.evidence_seed import seed_job, seed_detail, seed_company_page, seed_cli_row
from where_my_job.store import db, runs, bundles, evidence
from where_my_job.errors import InvalidInput

JOB = "boss:SYN0001aaaa"

def _keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _keys(v)

def _size(obj):
    return len(json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8"))

def _bundle(conn, clock, ids, state="complete", unknowns=()):
    with db.write_tx(conn):
        run_id = runs.create(conn, clock, kind="deepdive", config={}, planned=1)
        return bundles.create(conn, clock, job_id=JOB, run_id=run_id, evidence_ids=list(ids),
                              acquisition_state=state, unknowns=list(unknowns))

def test_bundle_create_immutable_and_current(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    c = seed_company_page(conn, clock, "boss:SYNCO1")
    b1 = _bundle(conn, clock, [d, c, d])
    cur = bundles.current_for_job(conn, JOB)
    assert cur["bundle_id"] == b1 and cur["bundle_version"] == 1 and cur["evidence_ids"] == [d, c]
    assert cur["fact_sighting_id"] is not None
    clock.advance(1)
    with db.write_tx(conn):
        b2 = bundles.derive(conn, clock, base_bundle_id=b1, extra_evidence_ids=["ev_extra_0001"])
    cur2 = bundles.current_for_job(conn, JOB)
    assert cur2["bundle_id"] == b2 and cur2["parent_bundle_id"] == b1 and cur2["bundle_version"] == 2
    assert cur2["evidence_ids"] == [d, c, "ev_extra_0001"] and cur2["acquisition_state"] == "complete"
    assert bundles.get(conn, b1)["evidence_ids"] == [d, c]

def test_bundle_payload_is_minimized(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    b = _bundle(conn, clock, [d], "partial", ["company_page: 未采集"])
    payload = bundles.payload(conn, b)
    text = json.dumps(payload, ensure_ascii=False)
    assert _size(payload) <= bundles.BUNDLE_MAX_BYTES and "full_text" not in set(_keys(payload))
    assert payload["evidence"][0]["full_text_state"] == "present"
    for banned in ("security_id", "SYN-SECURITY", "SYN.lid", "SYNBOSS"):
        assert banned not in text
    assert payload["signals"]["observation_span"]["hits"] == 1 and payload["acquisition_state"] == "partial"
    assert payload["signals"]["observation_as_of"] == "2026-09-14T12:00:00.000000Z"
    assert "无法确认发布日期" in payload["signals"]["up_date"]["statement"]
    assert payload["evidence_total"] == 1 and payload["next_evidence_offset"] is None

def test_old_bundle_keeps_frozen_fact_after_new_import(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    old = _bundle(conn, clock, [d])
    before = bundles.payload(conn, old)
    clock.advance(3600)
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1", fixture_index=1)
    after = bundles.payload(conn, old)
    for key in ("title", "company_name", "city", "district", "salary_text", "salary_lo", "salary_hi",
                "salary_period", "pay_months", "exp", "degree", "skills_json", "fact_revision", "fact_sighting_id"):
        assert after["fact"][key] == before["fact"][key], key
    assert before["fact"]["title"] == "AI产品经理" and before["fact"]["company_name"] == "合成科技一号"
    assert after["signals"]["observation_span"]["hits"] == 2
    new = _bundle(conn, clock, [d])
    assert bundles.payload(conn, new)["fact"]["title"] == "产品经理（校招）"

def test_single_huge_excerpt_truncated_in_store_and_bundle(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB, excerpt="长" * 70000)
    assert conn.execute("select length(excerpt) from evidence where evidence_id=?", (d,)).fetchone()[0] == evidence.EXCERPT_MAX
    payload = bundles.payload(conn, _bundle(conn, clock, [d]))
    item = payload["evidence"][0]
    assert len(item["excerpt"]) == bundles.EXCERPT_IN_BUNDLE and item["excerpt_truncated"] is True
    assert payload["truncated"] is True

def test_many_evidence_payload_capped_with_continuation(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    ids = []
    for i in range(40):
        obj = dict(load_fixture("evidence/web_page.json"), idempotency_key=f"syn-ev-many-{i:04d}",
                   url=f"https://example.com/many/{i}", excerpt="证" * 16000,
                   structured={"summary": "要" * 2000, "title": "题" * 2000})
        with db.write_tx(conn):
            eid, _ = evidence.insert_external(conn, clock, obj, origin="agent")
        ids.append(eid)
    b = _bundle(conn, clock, ids)
    payload = bundles.payload(conn, b)
    assert _size(payload) <= bundles.BUNDLE_MAX_BYTES and payload["truncated"] is True
    assert payload["evidence_total"] == 40
    offset = payload["next_evidence_offset"]
    assert isinstance(offset, int) and 0 < offset < 40
    assert [e["evidence_id"] for e in payload["evidence"]] == ids[:offset]
    page = bundles.evidence_page(conn, b, limit=200, offset=offset)
    assert page["total"] == 40 and page["truncated"] is False
    assert [e["evidence_id"] for e in page["items"]] == ids[offset:]
    assert "full_text" not in set(_keys(page))

def test_large_whitelisted_structured_still_capped(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    long = "字" * 2000
    detail_struct = {k: long for k in ("boss_title", "boss_active_status", "ld_json_upDate", "ld_upDate_raw",
                                       "ld_datePosted_raw", "detail_salary_text", "detail_exp", "detail_degree")}
    detail_struct["tags"] = ["签" * 200] * 64
    company_struct = {k: long for k in ("industry", "scale", "stage", "ld_json_upDate", "ld_upDate_raw",
                                        "job_count_raw", "boss_count_raw")}
    d = seed_detail(conn, clock, JOB, structured=detail_struct)
    c = seed_cli_row(conn, clock, "company_page_row.json", job_id=None, company_id="boss:SYNCO1",
                     key="seed-company-large-0001", structured=company_struct)
    b = _bundle(conn, clock, [d, c])
    payload = bundles.payload(conn, b)
    assert _size(payload) <= bundles.BUNDLE_MAX_BYTES and payload["truncated"] is True
    assert payload["evidence_total"] == 2 and payload["next_evidence_offset"] is not None
    rest = bundles.evidence_page(conn, b, limit=2, offset=payload["next_evidence_offset"])
    assert [e["evidence_id"] for e in rest["items"]] == [d, c][payload["next_evidence_offset"]:]

def test_evidence_page_placeholders_and_argument_checks(conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    b = _bundle(conn, clock, [d, "ev_missing_0001"])
    page = bundles.evidence_page(conn, b, limit=1, offset=1)
    assert page["items"] == [{"evidence_id": "ev_missing_0001", "missing": True}]
    assert page["total"] == 2 and page["offset"] == 1 and page["truncated"] is False
    with pytest.raises(InvalidInput):
        bundles.evidence_page(conn, b, limit=0, offset=0)
    with pytest.raises(InvalidInput) as ei:
        bundles.evidence_page(conn, "bundle_nope", limit=1, offset=0)
    assert ei.value.code == "NOT_FOUND"
