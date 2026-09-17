from __future__ import annotations
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .. import Issue, Facts

def check(obj: dict, facts: Facts) -> list[Issue]:
    issues: list[Issue] = []
    tz = obj.get("timezone_assumption")
    if tz is not None:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            issues.append(Issue("SEMANTIC_INVALID", "$.timezone_assumption", f"未知时区 {tz}"))
    return issues
