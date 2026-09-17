from where_my_job.normalize.fact import Fact
from where_my_job.rules.fields import FIELDS, get_value, derived_text

def _fact(**kw):
    base = dict(title="AI产品经理", company_name="合成一号", city="合肥", district=None, salary_text="15-25K",
                salary_lo=15.0, salary_hi=25.0, salary_currency="CNY", salary_period="month", pay_months=None,
                exp="1-3年", degree="本科", skills=("AI产品", "Agent"), job_labels=(), welfare=(),
                company_scale="100-499人", company_stage="A轮", company_industry="人工智能",
                boss_title="产品总监", boss_active_status=None, unknowns=())
    base.update(kw)
    return Fact(**base)

def test_registry_types():
    assert FIELDS["title"] == "text" and FIELDS["salary_lo"] == "num" and FIELDS["pay_months"] == "int"
    assert FIELDS["skills"] == "list" and FIELDS["title_skills"] == "text" and FIELDS["title_skills_industry"] == "text"
    assert "security_id" not in FIELDS and "raw_json" not in FIELDS

def test_derived_text_fixed_order():
    f = _fact()
    assert derived_text(f, "title_skills") == "AI产品经理 AI产品 Agent"
    assert derived_text(f, "title_skills_industry") == "AI产品经理 AI产品 Agent 人工智能"
    assert derived_text(_fact(title=None, skills=(), company_industry=None), "title_skills_industry") is None

def test_get_value_none_for_missing():
    assert get_value(_fact(salary_lo=None), "salary_lo") is None
    assert get_value(_fact(salary_lo=None), "salary_lo") is None
    assert get_value(_fact(), "exp") == "1-3年"
    assert get_value(_fact(), "skills") == ("AI产品", "Agent")
