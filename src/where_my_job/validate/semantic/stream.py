# src/where_my_job/validate/semantic/stream.py
from __future__ import annotations
from .. import Issue, Facts
from ...streams import builtin as b

def check(obj: dict, facts: Facts) -> list[Issue]:
    issues = []
    for path, msg in b.definition_problems(obj):
        code = "UNSUPPORTED_SETTING" if path in ("$.projection", "$.latest_by") else "SEMANTIC_INVALID"
        issues.append(Issue(code, path, msg))
    if obj.get("stream") == b.APPLICATIONS_STREAM:
        issues.append(Issue("RESERVED_KEY", "$.stream", "applications 是内置流，不能重新声明"))
    return issues
