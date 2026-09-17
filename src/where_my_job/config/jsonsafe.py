"""严格 JSON：拒绝非有限数与过深嵌套。纯函数，importer 与 loader 共用。"""
from __future__ import annotations
import json, math

MAX_DEPTH = 64

class JsonSafetyError(ValueError):
    pass

def _reject_constant(value):
    raise JsonSafetyError(f"不允许的 JSON 常量 {value}")

def check_finite(value, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise JsonSafetyError(f"JSON 嵌套超过 {MAX_DEPTH} 层")
    if isinstance(value, float) and not math.isfinite(value):
        raise JsonSafetyError("JSON 数值必须有限")
    if isinstance(value, dict):
        for child in value.values():
            check_finite(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            check_finite(child, depth + 1)

def loads_strict(payload: bytes):
    """UnicodeDecodeError 与 json.JSONDecodeError 原样抛出；安全问题抛 JsonSafetyError。"""
    text = payload.decode("utf-8")
    try:
        obj = json.loads(text, parse_constant=_reject_constant)
    except RecursionError as e:
        raise JsonSafetyError("JSON 嵌套过深") from e
    check_finite(obj)
    return obj
