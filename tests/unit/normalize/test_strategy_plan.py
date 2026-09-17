# tests/unit/normalize/test_strategy_plan.py
import time
import pytest
from where_my_job.normalize.strategy_plan import expand_plan, PlanError, PlanLimitExceeded, DEFAULT_MAX_PAGES_PER_RUN

def _st(searches, budget=None):
    return {"schema_version": 1, "name": "t", "searches": searches,
            "budget": budget or {"pause_between_actions_sec": [12, 22]}}

def test_defaults_first_page_and_cap_20():
    plan = expand_plan(_st([{"keywords": ["AI产品经理"], "cities": ["合肥"]}]))
    assert len(plan.tasks) == 1 and plan.tasks[0].page == 1 and plan.cap == DEFAULT_MAX_PAGES_PER_RUN == 20
    t = plan.tasks[0]
    assert (t.keyword, t.city_name, t.city_code, t.filters) == ("AI产品经理", "合肥", "101220100", {})

def test_string_label_and_array_forms_give_same_plan():
    a = expand_plan(_st([{"keywords": ["k"], "cities": ["合肥"], "boss_filters": {"experience": "105"}}]))
    b = expand_plan(_st([{"keywords": ["k"], "cities": ["合肥"], "boss_filters": {"experience": "3-5年"}}]))
    c = expand_plan(_st([{"keywords": ["k"], "cities": ["101220100"], "boss_filters": {"experience": ["3-5年", "105"]}}]))
    assert [t.filters for t in a.tasks] == [t.filters for t in b.tasks] == [t.filters for t in c.tasks] == [{"experience": "105"}]
    assert a.tasks[0].filter_labels == {"experience": "3-5年"}

def test_multi_value_filters_expand_combinations_and_dedupe_duplicates():
    plan = expand_plan(_st([
        {"keywords": ["k", "k"], "cities": ["合肥", "101220100"], "pages": 2, "boss_filters": {"salary": ["405", "406"]}},
    ]))
    assert len(plan.tasks) == 4          # 1 关键词 × 1 城 × 2 薪资 × 2 页（重复关键词/同城不同写法去重）
    assert {t.filters["salary"] for t in plan.tasks} == {"405", "406"}

def test_84_rejected_80_passes():
    cities = ["合肥", "上海", "北京", "深圳", "广州", "杭州"]
    with pytest.raises(PlanLimitExceeded) as ei:
        expand_plan(_st([{"keywords": [f"k{i}" for i in range(7)], "cities": cities, "pages": 2}],
                        {"max_pages_per_run": 80, "pause_between_actions_sec": [12, 22]}))
    assert ei.value.cap == 80 and ei.value.seen == 81 and ei.value.path == "$.searches"
    from where_my_job.errors import InvalidInput
    assert isinstance(ei.value, InvalidInput) and ei.value.exit_code == 1 and ei.value.code == "SEMANTIC_INVALID"
    ok = expand_plan(_st([{"keywords": [f"k{i}" for i in range(5)], "cities": cities[:4], "pages": 4}],
                         {"max_pages_per_run": 80, "pause_between_actions_sec": [12, 22]}))
    assert len(ok.tasks) == 80

def test_huge_input_stops_at_81_without_materializing():
    st = _st([{"keywords": [f"k{i}" for i in range(100000)], "cities": ["合肥", "上海", "北京", "深圳", "广州", "杭州", "武汉"],
               "pages": 80, "boss_filters": {"salary": ["402", "403", "404", "405", "406", "407"]}}],
             {"max_pages_per_run": 80, "pause_between_actions_sec": [12, 22]})
    started = time.monotonic()
    with pytest.raises(PlanLimitExceeded) as ei:
        expand_plan(st)
    assert ei.value.seen == 81 and time.monotonic() - started < 1.0

def test_unknown_city_and_code_paths():
    with pytest.raises(PlanError) as ei:
        expand_plan(_st([{"keywords": ["k"], "cities": ["合肥", "火星"]}]))
    assert ei.value.path == "$.searches[0].cities[1]"
    with pytest.raises(PlanError) as ei:
        expand_plan(_st([{"keywords": ["k"], "cities": ["合肥"], "boss_filters": {"experience": ["105", "999"]}}]))
    assert ei.value.path == "$.searches[0].boss_filters.experience[1]"
    with pytest.raises(PlanError) as ei:
        expand_plan(_st([{"keywords": ["k"], "cities": ["合肥"], "boss_filters": {"experience": "999"}}]))
    assert ei.value.path == "$.searches[0].boss_filters.experience"

def test_plan_exposes_scan_contract_fields():
    """子计划 05 的 dry-run 与 scan 依赖这些派生字段。"""
    strat = {"schema_version": 1, "name": "合成两页",
             "searches": [{"keywords": ["AI产品经理"], "cities": ["合肥"], "pages": 2,
                           "boss_filters": {"experience": "104"}}],
             "budget": {"max_pages_per_run": 5, "pause_between_actions_sec": [15, 30]}}
    plan = expand_plan(strat)
    assert plan.name == "合成两页" and plan.pause == (15.0, 30.0) and plan.actions == 2
    assert plan.estimated_seconds() == [15, 30]
    t1, t2 = plan.tasks
    assert t1.city == "合肥" and t1.task_key == "AI产品经理|101220100|experience=104|p1"
    assert t2.task_key.endswith("|p2") and t1.task_key != t2.task_key
    assert len({t.task_key for t in plan.tasks}) == plan.actions


def test_strategy_carries_its_own_city_codes():
    """城市名→码的映射写在策略文件里：validate strategy 走的是无 context 的纯路径，
    数据目录里的配置到不了这儿；映射跟着用它的策略走，才能被同一份 schema 校验。"""
    from where_my_job.normalize.strategy_plan import expand_plan
    s = {"schema_version": 1, "name": "t", "city_codes": {"成都": "101270100"},
         "searches": [{"keywords": ["AI产品经理"], "cities": ["成都", "101190100", "合肥"], "pages": 2}],
         "budget": {"pause_between_actions_sec": [12, 20]}}
    plan = expand_plan(s)
    assert plan.actions == 6
    assert [t.city_code for t in plan.tasks][::2] == ["101270100", "101190100", "101220100"]
    assert [t.city_name for t in plan.tasks][::2] == ["成都", "101190100", "合肥"]
