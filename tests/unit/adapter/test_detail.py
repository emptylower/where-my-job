# tests/unit/adapter/test_detail.py
from tests.conftest import load_fixture
from where_my_job.adapter.detail import parse_job_detail, parse_company_page, PARSER_VERSION

def test_job_detail_ok_complete_with_raw_and_normalized_keys():
    d = parse_job_detail(load_fixture("pages/job_detail_ok.json"))
    assert d.completeness == "complete" and d.jd.startswith("负责 AI 产品")
    assert d.structured["ld_upDate_raw"] == d.structured["ld_json_upDate"] == "2026-09-01"
    assert d.structured["ld_datePosted_raw"] == "2026-08-15" and d.structured["tags"] == ["AI产品", "Agent", "B端产品"]
    assert "text_truncated" not in d.structured

def test_truncated_page_is_partial():
    d = parse_job_detail(load_fixture("pages/job_detail_truncated.json"))
    assert d.completeness == "partial" and "text_truncated" in d.unknowns

def test_garbage_is_unparsed_but_keeps_text():
    d = parse_job_detail(load_fixture("pages/job_detail_garbage.json"))
    assert d.completeness == "unparsed" and d.jd is None and "jd" in d.unknowns and d.full_text.startswith("首页")

def test_company_counts_read_the_number_before_the_label():
    """平台把数字写在标签前面、两个数连写在页头：`22在招职位3位BOSS`。"""
    c = parse_company_page(load_fixture("pages/company_ok.json"))
    assert (c.structured["job_count_raw"], c.structured["job_count"]) == ("22", 22)
    assert (c.structured["boss_count_raw"], c.structured["boss_count"]) == ("3", 3)
    assert c.structured["ld_json_upDate"] == "2026-08-30" and c.completeness == "complete"

def test_company_counts_are_not_confused_by_a_second_label_on_the_page():
    """页面别处还有一处"在招职位 99"：只认页头那个两数连写的整体，不被旁证串扰。
    旧实现在这里会把紧跟标签的 3（BOSS 数）当成岗位数。"""
    c = parse_company_page({"page_text": "合成科技一号\n22在招职位3位BOSS\n公司简介\n在招职位 99\n查看全部22个职位",
                            "ldjson": []})
    assert (c.structured["job_count"], c.structured["boss_count"]) == (22, 3)

def test_company_counts_accept_a_thousands_separator():
    """捕获允许千分位逗号，规范化就必须也允许：两处口径必须一致。"""
    c = parse_company_page(load_fixture("pages/company_comma_count.json"))
    assert (c.structured["job_count_raw"], c.structured["job_count"]) == ("1,024", 1024)
    assert (c.structured["boss_count"], c.unknowns, c.completeness) == (7, [], "complete")

def test_company_counts_stay_strict_beyond_six_digits():
    """严格口径不放宽：去掉逗号之后超过六位仍然只留原文、不给规范值。"""
    c = parse_company_page({"page_text": "合成科技一号\n12345678在招职位3位BOSS\n公司简介", "ldjson": []})
    assert c.structured["job_count_raw"] == "12345678" and c.structured["job_count"] is None
    assert "job_count" in c.unknowns

def test_missing_company_counts_do_not_downgrade_completeness():
    """两个计数是公司页的附属信息：缺了要记进 unknowns，但不该把整份证据判成 partial。"""
    c = parse_company_page(load_fixture("pages/company_no_counts.json"))
    assert {"job_count", "boss_count"} <= set(c.unknowns)
    assert c.completeness == "complete"

def test_truncated_company_page_is_partial():
    """公司页降级的唯一原因是正文截断，与详情页一致。"""
    c = parse_company_page({"page_text": "合成科技一号\n22在招职位3位BOSS", "ldjson": [], "text_truncated": True})
    assert c.completeness == "partial" and "text_truncated" in c.unknowns

def test_company_page_without_text_is_unparsed():
    c = parse_company_page({"page_text": "", "ldjson": []})
    assert c.completeness == "unparsed"

def test_parser_version():
    assert PARSER_VERSION == "detail-v2.1"
