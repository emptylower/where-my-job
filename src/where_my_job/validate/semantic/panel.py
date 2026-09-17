# src/where_my_job/validate/semantic/panel.py
from __future__ import annotations
from .. import Issue, Facts
from ...config.columns import V_JOBS_COLUMNS

_OPS_TEXT = {"=", "!=", "~"}

def check(obj: dict, facts: Facts) -> list[Issue]:
    issues: list[Issue] = []
    for i, c in enumerate(obj["columns"]):
        if c not in V_JOBS_COLUMNS:
            issues.append(Issue("SEMANTIC_INVALID", f"$.columns[{i}]", f"不是公开列: {c}"))
    s = obj.get("sort")
    if s and s["by"] not in V_JOBS_COLUMNS:
        issues.append(Issue("SEMANTIC_INVALID", "$.sort.by", f"不是公开列: {s['by']}"))
    for i, f in enumerate(obj.get("filters") or []):
        col = f["column"]
        if col not in V_JOBS_COLUMNS:
            issues.append(Issue("SEMANTIC_INVALID", f"$.filters[{i}].column", f"不是公开列: {col}")); continue
        typ = V_JOBS_COLUMNS[col]
        if typ == "text" and f["op"] not in _OPS_TEXT:
            issues.append(Issue("SEMANTIC_INVALID", f"$.filters[{i}].op", "文本列只支持 =, !=, ~"))
        if typ != "text" and (f["op"] == "~" or isinstance(f["value"], str)):
            issues.append(Issue("SEMANTIC_INVALID", f"$.filters[{i}].value", "数值列需要数值且不支持 ~"))
    active = facts.active_streams
    if active is not None:                       # 只有注入了数据库事实时才判断注册状态
        timeline = obj.get("timeline") or {}
        for i, name in enumerate(timeline.get("streams") or []):
            if name != "applications" and name not in active:
                issues.append(Issue("SEMANTIC_INVALID", f"$.timeline.streams[{i}]", f"流 {name} 尚未注册"))
    return issues
