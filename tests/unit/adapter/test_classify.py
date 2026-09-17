import json
from tests.conftest import load_fixture
from where_my_job.adapter.classify import (classify_joblist, classify_body, body_note, Classified,
                                           RISK_TEXT_MARKERS, page_text_risk)

def test_success_with_items_and_has_more():
    c = classify_joblist(load_fixture("api/page1_ok.json"))
    assert c.kind == "success" and c.has_more is True and len(c.items) == 2 and c.code == 0

def test_last_page_success_has_more_false():
    c = classify_joblist(load_fixture("api/last_page_ok.json"))
    assert c.kind == "success" and c.has_more is False

def test_code_31_and_37_blocked_with_platform_code_only():
    c31 = classify_joblist(load_fixture("api/page2_code31.json"))
    c37 = classify_joblist(load_fixture("api/page2_code37.json"))
    assert (c31.kind, c31.code, c31.reason) == ("blocked", 31, "risk_response")
    assert (c37.kind, c37.code) == ("blocked", 37)
    assert not hasattr(c37, "message")

def test_message_keyword_blocked_even_with_unknown_code():
    c = classify_joblist({"code": 12345, "message": "访问行为异常，请完成验证", "zpData": None})
    assert c.kind == "blocked" and c.code == 12345

def test_empty_requires_has_more_exactly_false():
    assert classify_joblist(load_fixture("api/empty_ok.json")).kind == "empty"
    for fx in ("api/empty_has_more_missing.json", "api/empty_has_more_true.json", "api/empty_has_more_string.json"):
        c = classify_joblist(load_fixture(fx))
        assert c.kind == "unknown" and c.reason == "empty_without_end_marker", fx

def test_success_has_more_is_bool_or_none():
    d = load_fixture("api/page1_ok.json"); d["zpData"]["hasMore"] = "yes"
    c = classify_joblist(d)
    assert c.kind == "success" and c.has_more is None

def test_unknown_code_and_shapes():
    assert classify_joblist(load_fixture("api/unknown_code.json")).kind == "unknown"
    assert classify_joblist({"zpData": {}}).kind == "unknown"
    assert classify_joblist(["not", "a", "dict"]).kind == "unknown"
    assert classify_joblist(None).kind == "unknown"

def test_all_salary_blank_is_unauthenticated():
    assert classify_joblist(load_fixture("api/unauthenticated.json")).kind == "unauthenticated"

def test_real_http_status_paths():
    assert classify_joblist({}, http_status=401).kind == "unauthenticated"
    assert classify_joblist({}, http_status=403).kind == "blocked"
    assert classify_joblist({}, http_status=429).kind == "blocked"
    assert classify_joblist(load_fixture("api/page1_ok.json"), http_status=500).kind == "unknown"

def test_body_non_json_risk_page_blocked_other_unknown():
    assert classify_body(load_fixture("api/captcha_html.json")["body"]).kind == "blocked"
    assert classify_body("<html>random</html>").kind == "unknown"
    assert classify_body(None).kind == "unknown"

def test_page_text_risk_does_not_fire_on_job_titles():
    assert page_text_risk("职位描述\n芯片验证工程师，负责 UVM 验证平台") is False
    assert page_text_risk("请完成安全验证后继续访问") is True
    assert all(m != "验证" for m in RISK_TEXT_MARKERS)

def test_sentinel_message_never_kept():
    c = classify_joblist(load_fixture("api/sentinel_message.json"))
    assert c.kind == "blocked" and "LEAK" not in repr(c)

def test_body_note_reports_shape_without_any_job_content():
    """结构摘要只含分类码、条目数、平台状态码与 hasMore；岗位内容一个字都不进去。"""
    c = classify_body(json.dumps(load_fixture("api/page1_ok.json"), ensure_ascii=False))
    note = body_note(c)
    assert note == "body:success,items=2,code=0,has_more=true"
    blob = json.dumps(load_fixture("api/page1_ok.json"), ensure_ascii=False)
    for word in ("jobName", "brandName", "salaryDesc", "encryptJobId"):
        assert word not in note
    assert len(note) < 80 and blob != note
    assert body_note(Classified("unknown", None, "non_json")) == "body:unknown,items=0"
    assert body_note(Classified("blocked", 37, "risk_response")) == "body:blocked,items=0,code=37"
