# src/where_my_job/validate/semantic/event.py
"""事件输入文件的语义校验。只用 Facts 快照或调用方传入的已解析定义；不查库。
数据库层的纠错目标/末端/幂等比较与有效集合复核由 store.events.append 在写事务内再做。"""
from __future__ import annotations
from .. import Issue, Facts
from ...clock import parse_iso
from ...streams import builtin as b

_TIME_ERRORS = (ValueError, TypeError, OverflowError)

def issue_from(path: str, msg: str) -> Issue:
    """把 builtin 的 (path, message) 转成 Issue：时间解析失败是 SCHEMA_INVALID，其余是 SEMANTIC_INVALID。"""
    return Issue("SCHEMA_INVALID" if msg == b.DATETIME_MSG else "SEMANTIC_INVALID", path, msg)

def _time_issue(value, path: str) -> Issue | None:
    try:
        parse_iso(value)
        return None
    except _TIME_ERRORS:
        return Issue("SCHEMA_INVALID", path, b.DATETIME_MSG)

def time_issues(obj: dict) -> list[Issue]:
    out = []
    t = _time_issue(obj.get("occurred_at"), "$.occurred_at")
    if t: out.append(t)
    block = obj.get("corrected")
    if isinstance(block, dict) and "replacement_occurred_at" in block:
        t = _time_issue(block["replacement_occurred_at"], "$.corrected.replacement_occurred_at")
        if t: out.append(t)
    return out

def _all_application_ids(facts: Facts) -> frozenset[str]:
    out: set[str] = set()
    for ids in (facts.application_ids_by_job or {}).values():
        out |= set(ids)
    return frozenset(out)

def check(obj: dict, facts: Facts, definition: dict | None = None) -> list[Issue]:
    """definition 为 None 时从 facts.active_streams 取活动定义，并要求新业务事件绑定活动版本；
    调用方（service.events.validate_new_request）已按请求的 stream_revision 解析出定义时直接使用它。"""
    issues: list[Issue] = [i for i in time_issues(obj) if i.path == "$.occurred_at"]
    stream = obj["stream"]
    if definition is None:
        definition = (facts.active_streams or {}).get(stream)
        if definition is None:
            return issues + [Issue("NOT_FOUND", "$.stream", f"流 {stream} 未注册或未激活")]
        if obj["type"] != b.CORRECTED_TYPE and obj.get("stream_revision") != definition["stream_revision"]:
            issues.append(Issue("SEMANTIC_INVALID", "$.stream_revision",
                                f"新事件必须绑定流 {stream} 的活动版本 {definition['stream_revision']}"))
    if obj["subject_kind"] != definition["subject_kind"]:
        issues.append(Issue("SEMANTIC_INVALID", "$.subject_kind", f"流 {stream} 的主体类型是 {definition['subject_kind']}"))
    subject_id = obj.get("subject_id")
    if obj["subject_kind"] == "none" and subject_id is not None:
        issues.append(Issue("SEMANTIC_INVALID", "$.subject_id", "subject_kind=none 时 subject_id 必须为空"))
    is_first_applied = stream == b.APPLICATIONS_STREAM and obj["type"] == "applied"
    if obj["type"] == b.CORRECTED_TYPE:
        block = obj.get("corrected")
        if block is None:
            issues.append(Issue("SEMANTIC_INVALID", "$.corrected", "type=corrected 必须提供 corrected 块"))
        else:
            for path, msg in b.check_corrected_block(block):
                issues.append(issue_from(path, msg))
            if block.get("op") == "replace" and block.get("original_type") not in definition["types"]:
                issues.append(Issue("SEMANTIC_INVALID", "$.corrected.original_type", "不是该流的业务类型"))
            elif block.get("op") == "replace" and isinstance(block.get("replacement_payload"), dict):
                for path, msg in b.check_payload(definition, block["original_type"], block["replacement_payload"]):
                    issues.append(issue_from(path.replace("$.payload", "$.corrected.replacement_payload"), msg))
        if obj.get("payload"):
            issues.append(Issue("SEMANTIC_INVALID", "$.payload", "corrected 事件的 payload 必须为空对象，内容放在 corrected 块"))
        if obj["subject_kind"] != "none" and not subject_id:
            issues.append(Issue("SEMANTIC_INVALID", "$.subject_id", "纠错事件必须指明与目标相同的主体"))
        return issues
    if obj.get("corrected") is not None:
        issues.append(Issue("SEMANTIC_INVALID", "$.corrected", "只有 type=corrected 才能带 corrected 块"))
    for path, msg in b.check_payload(definition, obj["type"], obj["payload"]):
        issues.append(issue_from(path, msg))
    if is_first_applied:
        if subject_id is not None:
            issues.append(Issue("SEMANTIC_INVALID", "$.subject_id", "applied 由 CLI 创建投递身份，不要提供 subject_id"))
        job_id = obj["payload"].get("job_id")
        if job_id is not None and job_id not in facts.job_ids:
            issues.append(Issue("SUBJECT_MISSING", "$.payload.job_id", f"岗位不存在: {job_id}"))
        return issues
    kind = obj["subject_kind"]
    if kind == "none":
        return issues
    if not subject_id:
        issues.append(Issue("SEMANTIC_INVALID", "$.subject_id", "必须提供主体 ID"))
        return issues
    if kind == "job" and subject_id not in facts.job_ids:
        issues.append(Issue("SUBJECT_MISSING", "$.subject_id", f"岗位不存在: {subject_id}"))
    elif kind == "application" and subject_id not in _all_application_ids(facts):
        issues.append(Issue("SUBJECT_MISSING", "$.subject_id", f"投递身份不存在或没有有效 applied: {subject_id}"))
    # company 主体：Facts 未携带公司清单，由 store.events._check_subject 在写事务内检查
    return issues
