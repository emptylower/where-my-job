# src/where_my_job/validate/semantic/evidence.py
from __future__ import annotations
from ...clock import parse_iso
from .. import Issue, Facts

URL_REQUIRED_KINDS = ("web_page", "document")

def _time(obj: dict, key: str, issues: list[Issue]):
    if key not in obj:
        return None
    try:
        return parse_iso(obj[key])
    except (ValueError, TypeError, OverflowError) as exc:
        issues.append(Issue("SCHEMA_INVALID", f"$.{key}", f"无法解析为带时区的真实时间: {exc}"))
        return None

def check(obj: dict, facts: Facts) -> list[Issue]:
    issues: list[Issue] = []
    if obj["kind"] in URL_REQUIRED_KINDS and not obj.get("url"):
        issues.append(Issue("SEMANTIC_INVALID", "$.url", f"kind={obj['kind']} 必须提供 https URL"))
    if obj["kind"] == "user_statement" and obj.get("url"):
        issues.append(Issue("SEMANTIC_INVALID", "$.url", "user_statement 不得带 URL；有网页来源请用 web_page"))
    injected = facts.evidence_ids_by_job is not None
    job_id = obj.get("job_id")
    if injected and job_id is not None and job_id not in facts.job_ids:
        issues.append(Issue("NOT_FOUND", "$.job_id", f"岗位不存在: {job_id}"))
    captured = _time(obj, "captured_at", issues)
    published = _time(obj, "published_at", issues)
    if captured is not None and published is not None and published > captured:
        issues.append(Issue("SEMANTIC_INVALID", "$.published_at", "发布时间晚于采集时间"))
    return issues
