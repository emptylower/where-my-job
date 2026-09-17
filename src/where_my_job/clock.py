from __future__ import annotations
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol

class Clock(Protocol):
    def now(self) -> datetime: ...          # tz-aware UTC
    def monotonic(self) -> float: ...

class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic(self) -> float:
        return time.monotonic()

class FixedClock:
    def __init__(self, at: datetime, mono: float = 1000.0):
        assert at.tzinfo is not None
        self._at, self._mono = at, mono

    def now(self) -> datetime:
        return self._at

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> None:
        self._at += timedelta(seconds=seconds)
        self._mono += seconds

def iso_utc(dt: datetime) -> str:
    """规范 UTC 字符串：YYYY-MM-DDTHH:MM:SS.ffffffZ。"""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def parse_iso(s: str) -> datetime:
    """接受 'Z' 或 '+08:00' 后缀；无时区或非字符串报 ValueError。"""
    if not isinstance(s, str):
        raise ValueError("datetime must be a string")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError(f"naive datetime not allowed: {s}")
    return dt.astimezone(timezone.utc)
