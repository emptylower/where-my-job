# tests/unit/service/test_scan_plan_contract.py
"""05 只消费 02 的展开器与码表，不另起一套。"""
from tests.conftest import load_fixture
from where_my_job.service import scan_plan
from where_my_job.normalize import strategy_plan
from where_my_job.config import search_codes

def test_reexports_are_the_same_objects():
    assert scan_plan.expand_plan is strategy_plan.expand_plan
    assert scan_plan.compile_filter is search_codes.compile_filter and scan_plan.city_code is search_codes.city_code

def test_plan_shape_used_by_scan():
    plan = scan_plan.expand_plan(load_fixture("strategies/scan_salary_405.json"))
    assert plan.actions == 2 and len(plan.pause) == 2
    t = plan.tasks[0]
    for attr in ("keyword", "city", "city_code", "filters", "filter_labels", "page", "task_key"):
        assert hasattr(t, attr)
    assert {x.filters["salary"] for x in plan.tasks} == {"405", search_codes.compile_filter("salary", "20-50K").code}
    assert all(x.filters["experience"] == search_codes.compile_filter("experience", "经验不限").code for x in plan.tasks)

def test_80_allowed_84_rejected_by_the_same_expander():
    import pytest
    from where_my_job.errors import InvalidInput
    assert scan_plan.expand_plan(load_fixture("strategies/scan_matrix_80.json")).actions == 80
    with pytest.raises(InvalidInput):
        scan_plan.expand_plan(load_fixture("strategies/scan_matrix_84.json"))
