from __future__ import annotations
import json
from pathlib import Path
from ..errors import InvalidInput, EnvError, ErrorItem
from ..validate import validate, Facts
from .jsonsafe import loads_strict, JsonSafetyError

def _schema_error(message: str, path: str = "$") -> InvalidInput:
    return InvalidInput([ErrorItem("SCHEMA_INVALID", message, path)])

def read_json_file(path: Path | str) -> dict:
    path = Path(path)
    try:
        payload = path.read_bytes()
    except PermissionError as e:
        raise EnvError("PERMISSION_DENIED", f"无权读取 {path}") from e
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError) as e:
        raise _schema_error(f"无法读取 {path}: {e.strerror}") from e
    except OSError as e:
        raise EnvError("DISK_ERROR", f"读取失败 {path}: {e.strerror}") from e
    try:
        obj = loads_strict(payload)
    except UnicodeDecodeError as e:
        raise _schema_error(f"{path.name} 不是 UTF-8 文本") from e
    except json.JSONDecodeError as e:
        raise _schema_error(f"JSON 语法错误: {e.msg} (line {e.lineno})") from e
    except JsonSafetyError as e:
        raise _schema_error(str(e)) from e
    if not isinstance(obj, dict) or "schema_version" not in obj:
        raise _schema_error("顶层必须是对象且含 schema_version", "$.schema_version")
    return obj

def validate_object(kind: str, obj: dict, facts: Facts | None = None) -> dict:
    issues = validate(kind, obj, facts)
    if issues:
        raise InvalidInput([ErrorItem(i.code, i.message, i.path) for i in issues])
    return obj

def load_json_file(path: Path | str, kind: str, facts: Facts | None = None) -> dict:
    return validate_object(kind, read_json_file(path), facts)
