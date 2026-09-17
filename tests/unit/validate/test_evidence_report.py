# tests/unit/validate/test_evidence_report.py
import json
from tests.conftest import load_fixture
from where_my_job.validate import validate, Facts

JOB = "boss:SYN0001aaaa"
FACTS = Facts(job_ids=frozenset({JOB}),
              evidence_ids_by_job={JOB: frozenset({"ev_detail", "ev_web"})},
              bundle_ids_by_job={JOB: frozenset({"bundle_1"})})
EMPTY_DB = Facts(job_ids=frozenset(), evidence_ids_by_job={}, bundle_ids_by_job={})

def _rpt(name, **over):
    text = json.dumps(load_fixture(f"reports/{name}.json"), ensure_ascii=False)
    r = json.loads(text.replace("__BUNDLE_ID__", "bundle_1").replace("__DETAIL_EVIDENCE_ID__", "ev_detail"))
    r.update(over)
    return r

def test_evidence_web_page_ok_and_http_rejected():
    e = load_fixture("evidence/web_page.json")
    assert validate("evidence", e, FACTS) == []
    assert validate("evidence", dict(e, url="http://example.com/x"), FACTS)[0].path == "$.url"

def test_evidence_user_statement_needs_no_url_but_web_page_does():
    assert validate("evidence", load_fixture("evidence/user_statement.json"), FACTS) == []
    w = dict(load_fixture("evidence/web_page.json"))
    del w["url"]
    assert any(i.path == "$.url" for i in validate("evidence", w, FACTS))

def test_evidence_origin_cli_rejected_by_schema():
    e = dict(load_fixture("evidence/web_page.json"), origin="cli")
    assert validate("evidence", e, FACTS)[0].code == "SCHEMA_INVALID"

def test_evidence_job_existence_only_checked_when_facts_injected():
    e = load_fixture("evidence/web_page.json")
    issues = validate("evidence", e, EMPTY_DB)
    assert issues and issues[0].code == "NOT_FOUND" and issues[0].path == "$.job_id"
    assert validate("evidence", e, Facts()) == []

def test_evidence_times_compared_in_utc_and_bad_calendar_date():
    e = load_fixture("evidence/web_page.json")
    ok = dict(e, published_at="2026-09-14T11:00:00+08:00", captured_at="2026-09-14T10:00:00Z")
    assert validate("evidence", ok, FACTS) == []
    late = dict(e, published_at="2026-09-14T19:00:00+08:00", captured_at="2026-09-14T10:00:00Z")
    issues = validate("evidence", late, FACTS)
    assert issues[0].code == "SEMANTIC_INVALID" and issues[0].path == "$.published_at"
    bad = dict(e, captured_at="2026-02-30T10:00:00Z")
    issues = validate("evidence", bad, FACTS)
    assert issues[0].code == "SCHEMA_INVALID" and issues[0].path == "$.captured_at"

def test_report_only_supporting_ok():
    assert validate("report", _rpt("only_supporting"), FACTS) == []

def test_report_only_opposing_ok_and_both_empty_must_be_insufficient():
    assert validate("report", _rpt("only_opposing"), FACTS) == []
    bad = _rpt("both_empty")
    bad["authentic"]["conclusion"] = "倾向真实在招"
    issues = validate("report", bad, FACTS)
    assert issues[0].code == "REPORT_INCOMPLETE" and issues[0].path == "$.authentic.conclusion"
    assert validate("report", _rpt("both_empty"), FACTS) == []
    assert validate("report", _rpt("partial"), FACTS) == []

def test_report_positive_conclusion_needs_supporting_with_valid_ref():
    r = _rpt("only_opposing")
    r["authentic"]["conclusion"] = "倾向真实在招"
    assert validate("report", r, FACTS)[0].code == "REPORT_INCOMPLETE"
    r = _rpt("only_supporting")
    r["authentic"]["supporting"][0]["evidence_id"] = "ev_other_job"
    assert validate("report", r, FACTS)[0].code == "EVIDENCE_REF_INVALID"

def test_report_empty_arrays_need_unknowns_and_percent_forbidden():
    r = _rpt("both_empty")
    r["authentic"]["unknowns"] = []
    assert validate("report", r, FACTS)[0].path == "$.authentic.unknowns"
    r = _rpt("only_supporting")
    r["authentic"]["confidence"] = 0.8
    assert validate("report", r, FACTS)[0].code in ("UNKNOWN_FIELD", "SCHEMA_INVALID")
    r = _rpt("only_supporting")
    r["authentic"]["conclusion_label"] = "结论"
    assert validate("report", r, FACTS)[0].path == "$.authentic.conclusion_label"

def test_report_md_needs_four_nonempty_sections_bundle_ref_and_no_html():
    r = _rpt("only_supporting", report_md="## 招聘信号判断\n有\n## JD 翻译\n\n## 不匹配点\n有\n## 简历建议\n有\n")
    issues = validate("report", r, FACTS)
    assert issues[0].code == "REPORT_INCOMPLETE" and "JD 翻译" in issues[0].message
    assert validate("report", _rpt("only_supporting", bundle_id="bundle_zzz"), FACTS)[0].code == "NOT_FOUND"
    r = _rpt("only_supporting", report_md="## 招聘信号判断\n有\n## JD 翻译\n有\n## 不匹配点\n有\n## 简历建议\n有\n<script>x</script>")
    assert validate("report", r, FACTS)[0].path == "$.report_md"

def test_jd_and_mismatch_items_need_evidence_or_assumption():
    r = _rpt("only_supporting")
    r["jd_translation"]["sentences"][0].pop("evidence_id")
    r["jd_translation"]["sentences"][0].pop("assumption")
    issues = validate("report", r, FACTS)
    assert issues[0].code == "SCHEMA_INVALID" and issues[0].path.startswith("$.jd_translation.sentences[0]")
    r = _rpt("only_opposing")
    r["mismatches"][0]["assumption"] = "   "
    issues = validate("report", r, FACTS)
    assert issues[0].code == "SEMANTIC_INVALID" and issues[0].path == "$.mismatches[0].assumption"

def test_jd_and_mismatch_refs_checked_even_with_assumption():
    r = _rpt("only_supporting")
    r["jd_translation"]["sentences"][0]["evidence_id"] = "ev_other_job"
    issues = validate("report", r, FACTS)
    assert issues[0].code == "EVIDENCE_REF_INVALID"
    assert issues[0].path == "$.jd_translation.sentences[0].evidence_id"
    r = _rpt("only_supporting")
    r["mismatches"][0]["evidence_id"] = "ev_other_job"
    assert validate("report", r, FACTS)[0].path == "$.mismatches[0].evidence_id"

def test_report_rejects_percentages_in_signal_text_only():
    r = _rpt("only_supporting")
    r["authentic"]["supporting"][0]["claim"] += "，真实概率 85%"
    issues = validate("report", r, FACTS)
    assert any(i.code == "SEMANTIC_INVALID" and i.path == "$.authentic.supporting[0].claim" for i in issues)
    r = _rpt("both_empty")
    r["authentic"]["unknowns"] = ["约百分之七十的线索无法核实"]
    assert any(i.path == "$.authentic.unknowns[0]" for i in validate("report", r, FACTS))
    r = _rpt("only_supporting")
    r["report_md"] = r["report_md"].replace("## 招聘信号判断\n", "## 招聘信号判断\n置信度 80％。\n", 1)
    assert any(i.path == "$.report_md" and "百分比" in i.message for i in validate("report", r, FACTS))
    r = _rpt("only_supporting")
    r["report_md"] = r["report_md"].replace("## 简历建议\n", "## 简历建议\n可写入把检查耗时降低 20% 的流程改进。\n", 1)
    assert not any("百分比" in i.message for i in validate("report", r, FACTS))
