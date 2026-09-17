import pytest
from tests.conftest import load_fixture
from where_my_job.normalize.legacy import map_legacy_record, LegacyRecordError
from where_my_job.normalize.fact import Fact, fact_hash

def _rec(i, **over):
    return dict(load_fixture("legacy/合肥_AI产品经理.json")["jobs"][i], **over)

def test_map_full_record():
    m = map_legacy_record(_rec(0))
    assert m.job_id == "boss:SYN0001aaaa" and m.legacy_job_id == "0000000000000001"
    assert m.company_id == "boss:SYNCO1" and m.company_name == "合成科技一号"
    f = m.fact
    assert f.title == "AI产品经理" and f.city == "合肥" and f.district == "蜀山区"
    assert (f.salary_lo, f.salary_hi, f.pay_months, f.salary_period) == (15.0, 25.0, 14, "month")
    assert f.exp == "1-3年" and f.degree == "本科" and f.skills == ("AI产品", "Agent", "B端产品")
    assert f.welfare == ("五险一金", "年终奖") and f.unknowns == ()
    assert m.raw_private["security_id"] == "SYN-SECURITY-1" and m.raw_private["lid"] == "SYN.lid.1"
    assert "security_id" not in f.to_json() and "lid" not in f.to_json()

def test_explicit_empty_skills_missing_company_and_daily_salary():
    m = map_legacy_record(_rec(2, skills=""))
    f = m.fact
    assert m.company_id is None and f.skills == () and "skills" in f.unknowns
    assert f.salary_period == "day" and f.salary_text == "300-400元/天"
    assert f.salary_lo is None and f.salary_hi is None
    assert {"salary_lo", "salary_hi"} <= set(f.unknowns) and "salary" not in f.unknowns

def test_standard_fact_turns_legacy_enum_into_unknown_but_raw_keeps_it():
    m = map_legacy_record(_rec(0, tags="3年以内 | 本科"))
    assert m.fact.exp is None and "exp" in m.fact.unknowns and m.raw_private["tags"] == "3年以内 | 本科"

@pytest.mark.parametrize("over", [
    {"job_link": "https://www.zhipin.com/job_detail/OTHER.html"},
    {"encrypt_job_id": ""},
    {"encrypt_job_id": "SYN/../x"},
    {"encrypt_brand_id": "SYN CO"},
    {"company_link": "https://www.zhipin.com/gongsi/OTHERCO.html"},
    {"tags": ["1-3年", "本科"]},
    {"title": 123},
])
def test_invalid_records_raise_record_error(over):
    with pytest.raises(LegacyRecordError):
        map_legacy_record(_rec(0, **over))

def test_non_dict_record_rejected():
    with pytest.raises(LegacyRecordError):
        map_legacy_record(["not", "a", "record"])

def test_fact_hash_stable_and_roundtrip():
    f = map_legacy_record(_rec(0)).fact
    assert Fact.from_json(f.to_json()) == f and fact_hash(f) == fact_hash(Fact.from_json(f.to_json()))
