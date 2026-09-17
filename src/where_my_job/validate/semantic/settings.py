from __future__ import annotations
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .. import Issue, Facts

def check(obj: dict, facts: Facts) -> list[Issue]:
    tz = obj.get("timezone")
    if tz is not None:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            return [Issue("SEMANTIC_INVALID", "$.timezone", f"未知时区 {tz}")]
    return []
