# src/where_my_job/validate/semantic/strategy.py
"""策略语义：间隔下限 + 纯展开器（码表、城市、去重后动作数上限）。"""
from __future__ import annotations
from .. import Issue, Facts
from ...normalize.strategy_plan import expand_plan, PlanError

MIN_PAUSE_SEC = 12.0

def check(obj: dict, facts: Facts) -> list[Issue]:
    issues: list[Issue] = []
    lo, hi = obj["budget"]["pause_between_actions_sec"]
    if lo < MIN_PAUSE_SEC:
        issues.append(Issue("SEMANTIC_INVALID", "$.budget.pause_between_actions_sec[0]", f"间隔下限不能低于 {MIN_PAUSE_SEC:.0f} 秒"))
    if hi < lo:
        issues.append(Issue("SEMANTIC_INVALID", "$.budget.pause_between_actions_sec[1]", "上限不能小于下限"))
    try:
        expand_plan(obj)
    except PlanError as e:
        issues.append(Issue("SEMANTIC_INVALID", e.path, e.message))
    return issues
