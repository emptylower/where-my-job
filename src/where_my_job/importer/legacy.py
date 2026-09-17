"""读取一个旧列表文件：一次读取字节、算哈希、严格解析、scraped_at 按时区假设转 UTC、逐条映射。"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from ..clock import iso_utc
from ..config.jsonsafe import loads_strict, JsonSafetyError
from ..ids import sha256_bytes
from ..normalize.legacy import map_legacy_record, MappedLegacy, LegacyRecordError

class LegacyFileError(ValueError):
    pass

@dataclass
class LegacyFile:
    path: Path
    name: str
    sha256: str
    keyword: str | None
    city: str | None
    filters: dict
    observed_at_raw: str | None
    observed_at_utc: str | None
    tz_assumption: str | None          # 仅当原值无时区、按假设解释时填写
    source_item_count: int
    records: list[tuple[int, MappedLegacy]] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)

def _to_utc(raw, tz: str) -> tuple[str | None, str | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        raise ValueError("scraped_at must be a string")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        return iso_utc(dt.replace(tzinfo=ZoneInfo(tz))), tz
    return iso_utc(dt), None

def read_legacy_file(path: Path, *, tz_assumption: str) -> LegacyFile:
    path = Path(path)
    try:
        payload = path.read_bytes()
        data = loads_strict(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, JsonSafetyError) as exc:
        raise LegacyFileError(f"{path.name}: 无法读取或解析 JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise LegacyFileError(f"{path.name}: 顶层必须是含 jobs 数组的对象")
    for key in ("keyword", "city"):
        if data.get(key) is not None and not isinstance(data[key], str):
            raise LegacyFileError(f"{path.name}: {key} 必须是文本")
    filters = data.get("filters") if data.get("filters") is not None else {}
    if not isinstance(filters, dict):
        raise LegacyFileError(f"{path.name}: filters 必须是对象")
    try:
        observed_utc, tz_used = _to_utc(data.get("scraped_at"), tz_assumption)
    except (ValueError, TypeError) as exc:
        raise LegacyFileError(f"{path.name}: scraped_at 无法解析: {exc}") from exc
    lf = LegacyFile(path=path, name=path.name, sha256=sha256_bytes(payload), keyword=data.get("keyword"),
                    city=data.get("city"), filters=filters, observed_at_raw=data.get("scraped_at"),
                    observed_at_utc=observed_utc, tz_assumption=tz_used, source_item_count=len(data["jobs"]))
    for i, rec in enumerate(data["jobs"]):
        try:
            lf.records.append((i, map_legacy_record(rec)))
        except LegacyRecordError as exc:
            lf.errors.append({"item_index": i, "message": str(exc)})
    return lf
