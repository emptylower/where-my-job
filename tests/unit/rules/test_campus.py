# tests/unit/rules/test_campus.py
from where_my_job.rules.campus import derive, CampusDecision

def test_explicit_override():
    d = derive("exclude", strategy_codes=["101"], scoring_allowlist=None, scoring_exclude_exps=[])
    assert d == CampusDecision("exclude", "explicit", {"strategy_codes": ["101"], "scoring_allowlist": None, "scoring_exclude_exps": []})
    assert derive("include", strategy_codes=[], scoring_allowlist=None, scoring_exclude_exps=["3-5年"]).value == "include"

def test_auto_include_when_no_experience_filter():
    d = derive("auto", strategy_codes=[], scoring_allowlist=None, scoring_exclude_exps=[])
    assert d.value == "include" and d.basis == "no_experience_filter"

def test_auto_include_when_any_no_experience_code():
    for code in ("101", "102", "108"):
        assert derive("auto", strategy_codes=[code, "105"], scoring_allowlist=None, scoring_exclude_exps=[]).value == "include"
    assert derive("auto", strategy_codes=[], scoring_allowlist=["经验不限", "1-3年"], scoring_exclude_exps=[]).value == "include"

def test_auto_exclude_when_only_year_bands():
    d = derive("auto", strategy_codes=["104", "105"], scoring_allowlist=None, scoring_exclude_exps=[])
    assert d.value == "exclude" and d.basis == "only_year_bands"
    d = derive("auto", strategy_codes=[], scoring_allowlist=["1-3年", "3-5年"], scoring_exclude_exps=[])
    assert d.value == "exclude"

def test_auto_union_of_strategy_and_scoring():
    d = derive("auto", strategy_codes=["104"], scoring_allowlist=["经验不限"], scoring_exclude_exps=[])
    assert d.value == "include" and d.basis == "union_contains_no_experience"

def test_auto_from_exclude_rules_complement():
    # 只有黑名单 3-5年/5-10年/10年以上 → 允许集含 经验不限 → include（交接 legacy 口径 → 478）
    d = derive("auto", strategy_codes=[], scoring_allowlist=None, scoring_exclude_exps=["3-5年", "5-10年", "10年以上"])
    assert d.value == "include" and d.basis == "union_contains_no_experience"
    d = derive("auto", strategy_codes=[], scoring_allowlist=None,
               scoring_exclude_exps=["经验不限", "在校生", "应届生", "在校/应届", "3-5年", "5-10年", "10年以上"])
    assert d.value == "exclude"

def test_zero_code_means_no_filter():
    assert derive("auto", strategy_codes=["0"], scoring_allowlist=None, scoring_exclude_exps=[]).basis == "no_experience_filter"
