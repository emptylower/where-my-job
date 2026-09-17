# tests/unit/rules/test_eval.py
import copy
import pytest
from where_my_job.rules import limits
from where_my_job.rules.eval import compile_scoring, evaluate_job, ScoringCompileError, CAMPUS_EXP
from tests.conftest import load_fixture
from tests.unit.rules.test_fields import _fact

@pytest.fixture
def cfg():
    return load_fixture("scoring.minimal.json")

@pytest.fixture
def scoring(cfg):
    return compile_scoring(cfg)

def test_classify_first_match_and_null_dir(scoring):
    r = evaluate_job(scoring, _fact(title="AI产品经理"))
    assert r.dir == "AI产品经理"
    r = evaluate_job(scoring, _fact(title="AI 全栈 实习产品经理", skills=("LLM",)))
    assert r.dir == "AI产品经理"          # 第一条已命中，不再看"实习"
    r = evaluate_job(scoring, _fact(title="实习 全栈", skills=("LLM",)))
    assert r.dir is None and r.classified is True and r.rule_score is None   # 命中 dir=null：明确不分类
    r = evaluate_job(scoring, _fact(title="会计"))
    assert r.dir is None and r.classified is False

def test_exclusion_only_on_true(scoring):
    r = evaluate_job(scoring, _fact(degree="硕士"))
    assert r.excluded is True and r.exclusion_reasons[0]["rule_id"] == "degree-limit"
    r = evaluate_job(scoring, _fact(degree=None))
    assert r.excluded is False and "degree" in r.unknowns

def test_score_contributions_groups_and_tier(scoring):
    r = evaluate_job(scoring, _fact(title="AI产品经理", skills=("Agent", "B端产品", "C端"), city="合肥"))
    ids = [c["rule_id"] for c in r.reasons]
    assert ids[0] == "base" and "agent-interest" in ids and "preferred-city" in ids
    grp = [c for c in r.reasons if c["rule_id"] == "group:domain"][0]
    assert grp["delta"] == 8 and grp["raw"] == 10 and grp["bounds"] == {"min": 0.0, "max": 8.0}
    assert [m["rule_id"] for m in grp["members"]] == ["b-side", "c-side"]
    assert all({"delta", "reason", "facts"} <= set(m) for m in grp["members"])
    assert r.rule_score == 60 + 12 + 8 + 3 and r.tier == "A"
    assert sum(c["delta"] for c in r.reasons) == r.rule_score        # 成员嵌套，不重复累加

def test_group_without_hits_still_applies_bounds(cfg):
    cfg["score"]["AI产品经理"]["groups"]["domain"] = {"min": 2, "max": 8}
    sc = compile_scoring(cfg)
    r = evaluate_job(sc, _fact(title="AI产品经理", skills=("Agent",), city="上海"))
    grp = [c for c in r.reasons if c["rule_id"] == "group:domain"][0]
    assert grp["raw"] == 0 and grp["delta"] == 2 and grp["members"] == []
    assert r.rule_score == 60 + 12 + 2

def test_skills_hit_and_negative_and_fallback_tier(scoring):
    f = _fact(title="AI 全栈工程师", skills=("React", "Vue", "TypeScript", "Node", "Python", "Golang", "Redis", "MySQL"),
              salary_hi=50.0, city="上海")
    r = evaluate_job(scoring, f)
    assert r.dir == "AI全栈"
    hit = [c for c in r.reasons if c["rule_id"] == "stack-match"][0]
    assert hit["delta"] == 6 and hit["hits"][:3] == ["React", "Vue", "TS"]
    assert r.rule_score == 45 - 10 + 6 and r.tier == "C"
    r2 = evaluate_job(scoring, _fact(title="AI 全栈工程师", skills=(), salary_hi=50.0, city="上海"))
    assert r2.rule_score == 35 and r2.tier == "D"

def test_unknown_leaf_does_not_add(scoring):
    r = evaluate_job(scoring, _fact(title="AI 全栈", skills=("LLM",), salary_hi=None))
    assert all(c["rule_id"] != "high-pay-risk" for c in r.reasons) and "salary_hi" in r.unknowns

def test_experience_allowlist_excludes_others_but_not_campus_or_unknown(cfg):
    cfg["exclude"] = []
    cfg["experience_allowlist"] = ["1-3年"]
    sc = compile_scoring(cfg)
    r = evaluate_job(sc, _fact(exp="5-10年"))
    assert r.excluded is True and r.exclusion_reasons[0]["rule_id"] == "experience-allowlist"
    assert r.exclusion_reasons[0]["facts"] == {"exp": "5-10年", "allowed": ["1-3年"]}
    for campus in sorted(CAMPUS_EXP):
        assert evaluate_job(sc, _fact(exp=campus)).excluded is False          # 校园档交给 campus_policy
    assert evaluate_job(sc, _fact(exp=campus), campus_exclude=True).exclusion_reasons[0]["rule_id"] == "campus-policy"
    r = evaluate_job(sc, _fact(exp=None))
    assert r.excluded is False and "exp" in r.unknowns
    assert evaluate_job(sc, _fact(exp="1-3年")).excluded is False

def test_compile_rejects_bad_tiers_and_string_numbers(cfg):
    bad = copy.deepcopy(cfg); bad["tiers"] = {"S": 50, "A": 75}
    with pytest.raises(ScoringCompileError) as ei: compile_scoring(bad)
    assert "tiers" in ei.value.path
    bad = copy.deepcopy(cfg); bad["score"]["AI产品经理"]["base"] = "60"
    with pytest.raises(ScoringCompileError): compile_scoring(bad)
    bad = copy.deepcopy(cfg); bad["score"]["AI产品经理"]["rules"][0]["id"] = "b-side"
    with pytest.raises(ScoringCompileError): compile_scoring(bad)

@pytest.mark.parametrize("rid", ["base", "experience-allowlist", "campus-policy", "user-adjustment", "group:x"])
def test_reserved_rule_ids_rejected(cfg, rid):
    cfg["score"]["AI产品经理"]["rules"][0]["id"] = rid
    with pytest.raises(ScoringCompileError) as ei:
        compile_scoring(cfg)
    assert ei.value.path.endswith(".id")

def test_global_group_rejected(cfg):
    cfg["global"][0]["group"] = "domain"
    with pytest.raises(ScoringCompileError) as ei:
        compile_scoring(cfg)
    assert ei.value.path == "$.global[0].group"

def test_base_reason_required_and_non_blank(cfg):
    cfg["score"]["AI全栈"]["base_reason"] = "   "
    with pytest.raises(ScoringCompileError) as ei:
        compile_scoring(cfg)
    assert ei.value.path == "$.score.AI全栈.base_reason"

@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_numbers_must_be_finite(cfg, value):
    cfg["score"]["AI产品经理"]["base"] = value
    with pytest.raises(ScoringCompileError):
        compile_scoring(cfg)

def test_skills_per_category_and_cap_non_negative(cfg):
    cfg["score"]["AI全栈"]["rules"][1]["skills_hit"]["cap"] = -1
    with pytest.raises(ScoringCompileError) as ei:
        compile_scoring(cfg)
    assert ei.value.path.endswith("skills_hit.cap")

def test_config_size_counts_utf8_bytes(cfg, monkeypatch):
    import json
    chars = len(json.dumps(cfg, ensure_ascii=False))
    nbytes = len(json.dumps(cfg, ensure_ascii=False).encode("utf-8"))
    assert nbytes > chars
    monkeypatch.setattr(limits, "MAX_CONFIG_BYTES", chars)
    with pytest.raises(ScoringCompileError) as ei:
        compile_scoring(cfg)
    assert ei.value.path == "$"
