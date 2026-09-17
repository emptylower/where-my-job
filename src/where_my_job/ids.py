from __future__ import annotations
import hashlib, json, secrets
from datetime import datetime

def canonical_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def sha256_json(obj) -> str:
    return sha256_text(canonical_json(obj))

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def new_id(prefix: str, now: datetime, rand: bytes | None = None) -> str:
    """<prefix>_<13 位毫秒时间戳><16 hex 随机>。测试可注入 rand。"""
    ms = int(now.timestamp() * 1000)
    r = (rand or secrets.token_bytes(8)).hex()
    return f"{prefix}_{ms:013d}{r}"
