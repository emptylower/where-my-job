import pytest
from where_my_job.rules.ast import parse, evaluate, RuleParseError
from tests.unit.rules.test_fields import _fact

def test_leaf_match_eq_gte_lte_in():
    f = _fact()
    assert evaluate(parse({"field": "title", "match": "产品经理"}), f) is True
    assert evaluate(parse({"field": "title", "match": "agent", "flags": "i"}), f) is False
    assert evaluate(parse({"field": "title_skills", "match": "agent", "flags": "i"}), f) is True
    assert evaluate(parse({"field": "city", "eq": "合肥"}), f) is True
    assert evaluate(parse({"field": "salary_hi", "gte": 25}), f) is True
    assert evaluate(parse({"field": "salary_lo", "lte": 10}), f) is False
    assert evaluate(parse({"field": "degree", "in": ["硕士", "博士"]}), f) is False

def test_exists_and_unknown_propagation():
    f = _fact(salary_lo=None, degree=None)
    assert evaluate(parse({"field": "salary_lo", "exists": True}), f) is False
    assert evaluate(parse({"field": "salary_lo", "gte": 10}), f) is None
    assert evaluate(parse({"not": {"field": "degree", "in": ["硕士"]}}), f) is None
    assert evaluate(parse({"all": [{"field": "city", "eq": "合肥"}, {"field": "degree", "eq": "本科"}]}), f) is None
    assert evaluate(parse({"all": [{"field": "city", "eq": "上海"}, {"field": "degree", "eq": "本科"}]}), f) is False
    assert evaluate(parse({"any": [{"field": "city", "eq": "合肥"}, {"field": "degree", "eq": "本科"}]}), f) is True
    assert evaluate(parse({"any": [{"field": "city", "eq": "上海"}, {"field": "degree", "eq": "本科"}]}), f) is None

def test_type_strictness():
    with pytest.raises(RuleParseError) as ei:
        parse({"field": "salary_lo", "gte": "60"})
    assert ei.value.path.endswith(".gte")
    with pytest.raises(RuleParseError):
        parse({"field": "salary_lo", "match": "1"})          # match 只作用于文本
    with pytest.raises(RuleParseError):
        parse({"field": "skills", "eq": "AI"})               # list 字段不能 eq
    with pytest.raises(RuleParseError):
        parse({"field": "nope", "eq": 1})                    # 不在注册表
    with pytest.raises(RuleParseError):
        parse({"field": "title", "eq": "x", "match": "y"})   # 多个算子

def test_numeric_constants_must_be_finite():
    for bad in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(RuleParseError):
            parse({"field": "salary_hi", "gte": bad})
        with pytest.raises(RuleParseError):
            parse({"field": "salary_hi", "eq": bad})
        with pytest.raises(RuleParseError):
            parse({"field": "salary_hi", "in": [1, bad]})

def test_depth_limit_and_flags():
    node = {"field": "title", "eq": "x"}
    for _ in range(8):
        node = {"not": node}
    with pytest.raises(RuleParseError):
        parse(node)
    with pytest.raises(RuleParseError):
        parse({"field": "title", "match": "x", "flags": "x"})

def test_regex_precompiled_and_length_limited():
    with pytest.raises(RuleParseError):
        parse({"field": "title", "match": "a" * 300})
    with pytest.raises(RuleParseError):
        parse({"field": "title", "match": "("})
