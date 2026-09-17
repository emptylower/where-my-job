# tests/unit/store/test_evidence_store.py
import json
import pytest
from tests.conftest import load_fixture
from tests.helpers.evidence_seed import seed_job, seed_detail, seed_company_page, seed_cli_row
from where_my_job.store import db, evidence
from where_my_job.errors import InvalidInput

A, B = "boss:SYN0001aaaa", "boss:SYN0002bbbb"
PHONE = "1" + "38" + "0" * 8          # 运行时拼接：源码不含完整手机号样式，避免发行扫描命中

def _keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _keys(v)

def test_insert_is_idempotent_and_conflicts_on_any_semantic_change(conn, clock):
    seed_job(conn, clock, A, company_id="boss:SYNCO1")
    seed_job(conn, clock, B, company_id="boss:SYNCO1", fixture_index=1)
    e = load_fixture("evidence/web_page.json")
    with db.write_tx(conn):
        a, created_a = evidence.insert_external(conn, clock, e, origin="agent")
        b, created_b = evidence.insert_external(conn, clock, e, origin="agent")
    assert a == b and a.startswith("ev_") and created_a is True and created_b is False
    for change in ({"excerpt": "改了内容"}, {"source_note": "换了来源说明"}, {"job_id": B},
                   {"published_at": "2026-09-02T09:30:00+08:00"}):
        with pytest.raises(InvalidInput) as ei:
            with db.write_tx(conn):
                evidence.insert_external(conn, clock, dict(e, **change), origin="agent")
        assert ei.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            evidence.insert_external(conn, clock, e, origin="user")
    assert ei.value.code in ("IDEMPOTENCY_CONFLICT", "SEMANTIC_INVALID")
    assert conn.execute("select count(*) from evidence").fetchone()[0] == 1

def test_subject_relation_checked_inside_store(conn, clock):
    seed_job(conn, clock, A, company_id="boss:SYNCO1")
    seed_job(conn, clock, B, company_id="boss:SYNCO2", fixture_index=1)
    e = dict(load_fixture("evidence/web_page.json"), company_id="boss:SYNCO2", idempotency_key="syn-ev-rel-0001")
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            evidence.insert_external(conn, clock, e, origin="agent")
    assert ei.value.code == "EVIDENCE_REF_INVALID" and ei.value.path == "$.company_id"
    lone = dict(load_fixture("evidence/web_page.json"), idempotency_key="syn-ev-rel-0002")
    lone.pop("job_id")
    lone["company_id"] = "boss:SYNCO9"
    with pytest.raises(InvalidInput) as ei:
        with db.write_tx(conn):
            evidence.insert_external(conn, clock, lone, origin="agent")
    assert ei.value.code == "NOT_FOUND" and ei.value.path == "$.company_id"
    assert conn.execute("select count(*) from evidence").fetchone()[0] == 0

def test_public_row_projects_whitelist_and_strips_url(conn, clock):
    seed_job(conn, clock, A, company_id="boss:SYNCO1")
    structured = dict(load_fixture("evidence/detail_page_row.json")["structured"],
                      phone=PHONE, raw_html="<div>SYN-SECURITY-1</div>", text_truncated=True)
    eid = seed_detail(conn, clock, A, structured=structured,
                      url="https://www.zhipin.com/job_detail/SYN0001aaaa.html?lid=SYN.lid.1&securityId=SYN-SECURITY-1#top")
    row = evidence.get_public(conn, eid)
    assert row["url"] == "https://www.zhipin.com/job_detail/SYN0001aaaa.html"
    assert row["structured"]["boss_title"] == "产品总监" and row["structured"]["ld_upDate_raw"] == "2026-08-20 10:12:00"
    assert "phone" not in row["structured"] and "raw_html" not in row["structured"] and "text_truncated" not in row["structured"]
    assert row["structured_truncated"] is True
    assert "full_text" not in set(_keys(row)) and row["full_text_state"] == "present"
    text = json.dumps(row, ensure_ascii=False)
    assert PHONE not in text and "SYN-SECURITY" not in text and "SYN.lid" not in text
    assert evidence.get_full_text(conn, eid) == (load_fixture("evidence/detail_page_row.json")["full_text"], "present")
    assert evidence.structured_of(conn, eid)["text_truncated"] is True

def test_hash_computed_before_excerpt_truncation(conn, clock):
    seed_job(conn, clock, A, company_id="boss:SYNCO1")
    e = dict(load_fixture("evidence/web_page.json"), excerpt="长" * 20000, idempotency_key="syn-ev-long-0001")
    with db.write_tx(conn):
        eid, _ = evidence.insert_external(conn, clock, e, origin="agent")
        again, created = evidence.insert_external(conn, clock, e, origin="agent")
    assert again == eid and created is False
    assert conn.execute("select length(excerpt) from evidence where evidence_id=?", (eid,)).fetchone()[0] == evidence.EXCERPT_MAX

def test_ids_for_job_shares_only_company_level_evidence(conn, clock):
    seed_job(conn, clock, A, company_id="boss:SYNCO1")
    seed_job(conn, clock, B, company_id="boss:SYNCO1", fixture_index=1)
    d_a = seed_detail(conn, clock, A)
    d_b = seed_cli_row(conn, clock, "detail_page_row.json", job_id=B, company_id="boss:SYNCO1", key="seed-detail-b-with-company")
    c = seed_company_page(conn, clock, "boss:SYNCO1")
    assert evidence.ids_for_job(conn, A) == frozenset({d_a, c})
    assert evidence.ids_for_job(conn, B) == frozenset({d_b, c})
    rows, total, _ = evidence.list_public(conn, job_id=A, page=1, page_size=50)
    assert {r["evidence_id"] for r in rows} == {d_a, c} and total == 2

def test_list_public_paginates_and_validates_arguments(conn, clock):
    seed_job(conn, clock, A, company_id="boss:SYNCO1")
    for i in range(7):
        e = dict(load_fixture("evidence/web_page.json"), idempotency_key=f"syn-ev-page-{i:04d}", url=f"https://example.com/{i}")
        with db.write_tx(conn):
            evidence.insert_external(conn, clock, e, origin="agent")
    rows, total, truncated = evidence.list_public(conn, job_id=A, page=1, page_size=5)
    assert len(rows) == 5 and total == 7 and truncated is True
    with pytest.raises(InvalidInput):
        evidence.list_public(conn, job_id=A, page=1, page_size=201)
    with pytest.raises(InvalidInput):
        evidence.list_public(conn, job_id=A, company_id="boss:SYNCO1", page=1, page_size=5)

def test_insert_cli_requires_string_excerpt(conn, clock):
    seed_job(conn, clock, A, company_id="boss:SYNCO1")
    with pytest.raises(TypeError):
        with db.write_tx(conn):
            evidence.insert_cli(conn, clock, job_id=A, company_id=None, kind="job_detail_page",
                                url="https://www.zhipin.com/job_detail/SYN0001aaaa.html", captured_at=clock.now(),
                                excerpt=None, full_text=None, structured={}, parser_version="detail-v1",
                                completeness="unparsed", run_id=None, idempotency_key="syn-cli-none-0001")
