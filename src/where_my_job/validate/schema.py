from __future__ import annotations
import json
from functools import lru_cache
from importlib import resources
from jsonschema import Draft202012Validator
from . import Issue

@lru_cache(maxsize=None)
def _schema(kind: str) -> dict:
    ref = resources.files("where_my_job.config.schemas") / f"{kind}.schema.json"
    return json.loads(ref.read_text(encoding="utf-8"))

def _pointer(path_parts) -> str:
    out = "$"
    for p in path_parts:
        out += f"[{p}]" if isinstance(p, int) else f".{p}"
    return out

def schema_issues(kind: str, obj) -> list[Issue]:
    v = Draft202012Validator(_schema(kind))
    issues: list[Issue] = []
    for err in sorted(v.iter_errors(obj), key=lambda e: [str(x) for x in e.absolute_path]):
        path = _pointer(err.absolute_path)
        if err.validator == "additionalProperties":
            extra = sorted(set(err.instance) - set(err.schema.get("properties", {})))
            for k in extra:
                code = "UNSUPPORTED_SETTING" if (kind == "settings" and k == "retention_days") else "UNKNOWN_FIELD"
                issues.append(Issue(code, f"{path}.{k}", f"未知字段 {k}"))
        else:
            issues.append(Issue("SCHEMA_INVALID", path, err.message))
    return issues
