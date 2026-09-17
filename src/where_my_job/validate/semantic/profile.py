# src/where_my_job/validate/semantic/profile.py
from __future__ import annotations
from .. import Issue, Facts
from ...rules.campus import ALL_EXPS

def check(obj: dict, facts: Facts) -> list[Issue]:
    issues = []
    for i, e in enumerate((obj.get("targets") or {}).get("experience_scope") or []):
        if e not in ALL_EXPS:
            issues.append(Issue("SEMANTIC_INVALID", f"$.targets.experience_scope[{i}]", f"未知经验枚举 {e}"))
    return issues
