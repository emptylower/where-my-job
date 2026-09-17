# src/where_my_job/streams/builtin.py
"""事件流声明的纯逻辑：内置流、控制类型、字段类型检查、升版兼容性、定义哈希。无 IO。"""
from __future__ import annotations
import re
from ..ids import sha256_json
from ..clock import parse_iso

APPLICATIONS_STREAM = "applications"
CORRECTED_TYPE = "corrected"
CUSTOM_PREFIX = "custom."
FIELD_TYPES = ("string", "integer", "number", "boolean", "datetime", "enum")
APPLICATION_TYPES = ("applied", "replied", "interview", "offer", "rejected", "withdrawn")
SUBJECT_KINDS = ("job", "company", "application", "none")
DATETIME_MSG = "应为带时区且真实存在的 ISO 时间字符串"   # validate.semantic.event 据此把时间解析失败映射为 SCHEMA_INVALID
_TIME_ERRORS = (ValueError, TypeError, OverflowError)
_IDENT = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

APPLICATIONS_DEFINITION: dict = {
    "schema_version": 1,
    "stream": APPLICATIONS_STREAM,
    "stream_revision": 1,
    "subject_kind": "application",
    "types": {
        "applied":   {"required": ["job_id"], "fields": {"job_id": "string", "channel": "string", "note": "string"}},
        "replied":   {"required": [],         "fields": {"note": "string"}},
        "interview": {"required": [],         "fields": {"round": "string", "at": "datetime", "note": "string"}},
        "offer":     {"required": [],         "fields": {"note": "string"}},
        "rejected":  {"required": [],         "fields": {"note": "string"}},
        "withdrawn": {"required": [],         "fields": {"note": "string"}},
    },
}

# 控制事件 payload 结构（不在任何声明的 types 里，所有流内置）
CORRECTED_OPS = ("replace", "retract")

def is_identifier(s) -> bool:
    return isinstance(s, str) and bool(_IDENT.match(s))

def definition_hash(definition: dict) -> str:
    """只对语义内容哈希：忽略 schema_version 之外的展示字段（本版本没有）。"""
    core = {k: definition[k] for k in ("stream", "stream_revision", "subject_kind", "types")}
    return sha256_json(core)

def _field_type(spec) -> tuple[str, list | None]:
    if isinstance(spec, str):
        return spec, None
    if isinstance(spec, dict) and "enum" in spec:
        return "enum", list(spec["enum"])
    return "?", None

def check_value(spec, value) -> str | None:
    t, enum = _field_type(spec)
    if t == "string":
        return None if isinstance(value, str) else "应为字符串"
    if t == "integer":
        return None if (isinstance(value, int) and not isinstance(value, bool)) else "应为整数"
    if t == "number":
        return None if (isinstance(value, (int, float)) and not isinstance(value, bool)) else "应为数值"
    if t == "boolean":
        return None if isinstance(value, bool) else "应为布尔"
    if t == "datetime":
        if not isinstance(value, str): return DATETIME_MSG
        try: parse_iso(value); return None
        except _TIME_ERRORS: return DATETIME_MSG
    if t == "enum":
        return None if value in (enum or []) else f"应为 {enum} 之一"
    return f"未知字段类型 {t}"

def check_payload(definition: dict, type_name: str, payload: dict) -> list[tuple[str, str]]:
    """返回 [(path, message)]；空列表即通过。type_name 不能是 corrected。"""
    if type_name == CORRECTED_TYPE:
        return [("$.type", "corrected 是控制类型，用 corrected 块表达，不作为业务类型")]
    tdef = definition["types"].get(type_name)
    if tdef is None:
        return [("$.type", f"流 {definition['stream']} 版本 {definition['stream_revision']} 没有类型 {type_name}")]
    errs = []
    fields = tdef.get("fields", {})
    for req in tdef.get("required", []):
        if req not in payload:
            errs.append((f"$.payload.{req}", "缺少必填字段"))
    for k, v in payload.items():
        if k not in fields:
            errs.append((f"$.payload.{k}", "声明中没有此字段"))
            continue
        msg = check_value(fields[k], v)
        if msg: errs.append((f"$.payload.{k}", msg))
    return errs

def check_corrected_block(block: dict) -> list[tuple[str, str]]:
    errs = []
    if block.get("op") not in CORRECTED_OPS:
        errs.append(("$.corrected.op", f"op 应为 {CORRECTED_OPS} 之一"))
    if not isinstance(block.get("corrected_event_id"), str) or not block["corrected_event_id"]:
        errs.append(("$.corrected.corrected_event_id", "必须给目标事件 ID"))
    if block.get("op") == "replace":
        for k in ("original_type", "replacement_payload", "replacement_occurred_at"):
            if k not in block:
                errs.append((f"$.corrected.{k}", "replace 必须提供"))
        if "replacement_occurred_at" in block:
            try: parse_iso(block["replacement_occurred_at"])
            except _TIME_ERRORS: errs.append(("$.corrected.replacement_occurred_at", DATETIME_MSG))
        if "replacement_payload" in block and not isinstance(block["replacement_payload"], dict):
            errs.append(("$.corrected.replacement_payload", "应为对象"))
    else:
        for k in ("original_type", "replacement_payload", "replacement_occurred_at"):
            if k in block:
                errs.append((f"$.corrected.{k}", "retract 不接受此字段"))
    return errs

def definition_problems(d: dict) -> list[tuple[str, str]]:
    """静态声明问题（不含与注册表的兼容性）。"""
    errs = []
    stream = d.get("stream", "")
    if stream != APPLICATIONS_STREAM:
        if not stream.startswith(CUSTOM_PREFIX) or not is_identifier(stream[len(CUSTOM_PREFIX):]):
            errs.append(("$.stream", "自定义流名必须是 custom.<小写ASCII标识符>"))
    if d.get("subject_kind") not in SUBJECT_KINDS:
        errs.append(("$.subject_kind", f"应为 {SUBJECT_KINDS} 之一"))
    for key in ("projection", "latest_by"):
        if key in d:
            errs.append((f"$.{key}", "尚未支持（v1.1）"))
    types = d.get("types") or {}
    if not types:
        errs.append(("$.types", "至少声明一个业务类型"))
    for tname, tdef in types.items():
        if tname == CORRECTED_TYPE:
            errs.append((f"$.types.{tname}", "corrected 是保留控制类型，不能声明")); continue
        if not is_identifier(tname):
            errs.append((f"$.types.{tname}", "类型名必须是小写 ASCII 标识符")); continue
        fields = tdef.get("fields", {})
        for fname, spec in fields.items():
            if not is_identifier(fname):
                errs.append((f"$.types.{tname}.fields.{fname}", "字段名必须是小写 ASCII 标识符")); continue
            t, enum = _field_type(spec)
            if t not in FIELD_TYPES:
                errs.append((f"$.types.{tname}.fields.{fname}", f"类型应为 {FIELD_TYPES} 之一或 {{enum:[...]}}"))
            if t == "enum" and not enum:
                errs.append((f"$.types.{tname}.fields.{fname}.enum", "enum 必须列举至少一个值"))
        for req in tdef.get("required", []):
            if req not in fields:
                errs.append((f"$.types.{tname}.required", f"必填字段 {req} 未在 fields 中声明"))
    return errs

def compatibility_problems(old: dict, new: dict) -> list[str]:
    """升版规则：只允许加类型或可选字段；subject_kind、已有字段类型、必填集合、enum 不变；版本号 +1。"""
    p = []
    if new.get("stream") != old.get("stream"):
        p.append("stream 名不同")
    if new.get("stream_revision") != old.get("stream_revision") + 1:
        p.append(f"stream_revision 必须是 {old.get('stream_revision') + 1}")
    if new.get("subject_kind") != old.get("subject_kind"):
        p.append("subject_kind 不可变；不兼容语义请用新流名")
    for tname, otdef in old.get("types", {}).items():
        ntdef = new.get("types", {}).get(tname)
        if ntdef is None:
            p.append(f"类型 {tname} 不能删除"); continue
        if sorted(otdef.get("required", [])) != sorted(ntdef.get("required", [])):
            p.append(f"类型 {tname} 的 required 集合不可变")
        for fname, ospec in otdef.get("fields", {}).items():
            nspec = ntdef.get("fields", {}).get(fname)
            if nspec is None:
                p.append(f"类型 {tname} 字段 {fname} 不能删除"); continue
            if _field_type(ospec) != _field_type(nspec):
                p.append(f"类型 {tname} 字段 {fname} 类型或 enum 不可变")
        for fname in ntdef.get("fields", {}):
            if fname not in otdef.get("fields", {}) and fname in ntdef.get("required", []):
                p.append(f"类型 {tname} 新增字段 {fname} 不能是必填")
    return p
