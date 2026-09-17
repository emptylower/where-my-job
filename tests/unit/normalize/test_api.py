import pytest
from tests.conftest import load_fixture
from where_my_job.normalize.api import map_api_entry, ApiEntryError

def test_map_full_entry():
    raw = load_fixture("api/page1_ok.json")["zpData"]["jobList"][0]
    m = map_api_entry(raw)
    assert m.job_id == "boss:SYN0101aaaa" and m.source_job_id == "SYN0101aaaa" and m.legacy_job_id is None
    assert m.company_id == "boss:SYNCO1" and m.company_name == "合成科技一号"
    f = m.fact
    assert f.title == "AI产品经理" and f.city == "合肥" and f.district == "蜀山区"
    assert (f.salary_lo, f.salary_hi, f.pay_months, f.salary_period) == (15.0, 25.0, 14, "month")
    assert f.exp == "1-3年" and f.degree == "本科" and f.skills == ("AI产品", "Agent")
    assert f.boss_active_status == "在线" and f.boss_title == "产品总监"
    assert m.raw_private["securityId"] == "SYN-SECURITY-101" and "securityId" not in f.to_json()

def test_daily_salary_keeps_text_but_monthly_columns_null():
    raw = load_fixture("api/last_page_ok.json")["zpData"]["jobList"][0]
    m = map_api_entry(raw)
    assert m.company_id is None and m.fact.skills == ()
    assert m.fact.salary_period == "day" and m.fact.salary_text == "300-400元/天"
    assert (m.fact.salary_lo, m.fact.salary_hi) == (None, None)
    assert {"salary_lo", "salary_hi"} <= set(m.fact.unknowns) and "skills" in m.fact.unknowns

def test_invalid_ids_and_types_rejected():
    for bad in ({"jobName": "x"}, {"encryptJobId": "../x"}, {"encryptJobId": "SYN1", "encryptBrandId": "a b"},
                {"encryptJobId": "SYN1", "jobName": ["list"]}, {"encryptJobId": "SYN1", "skills": "not-a-list"}):
        with pytest.raises(ApiEntryError):
            map_api_entry(bad)
    with pytest.raises(ApiEntryError):
        map_api_entry("not a dict")
