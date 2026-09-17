from __future__ import annotations
import math, re
from dataclasses import dataclass

@dataclass(frozen=True)
class Salary:
    text: str | None
    lo: float | None
    hi: float | None
    currency: str | None
    period: str | None
    pay_months: int | None

_RANGE = r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)"
_MONTH_K = re.compile(rf"{_RANGE}K(?:·(\d+)薪)?")
_MONTH_YUAN = re.compile(rf"{_RANGE}元/月")
_DAY = re.compile(rf"{_RANGE}元/天")
_HOUR = re.compile(rf"{_RANGE}元/时")

def _unknown(text: str) -> Salary:
    return Salary(text, None, None, None, None, None)

def _build(text: str, lo_s: str, hi_s: str, scale: float, period: str, months_s: str | None) -> Salary:
    try:
        lo, hi = float(lo_s) / scale, float(hi_s) / scale
    except (ValueError, OverflowError):
        return _unknown(text)
    if not (math.isfinite(lo) and math.isfinite(hi)) or lo < 0 or lo > hi:
        return _unknown(text)
    months = None
    if months_s is not None:
        months = int(months_s)
        if months <= 0:
            return _unknown(text)
    return Salary(text, lo, hi, "CNY", period, months)

def parse_salary(text: str | None) -> Salary:
    t = text.strip() if isinstance(text, str) else ""
    if not t:
        return Salary(None, None, None, None, None, None)
    if m := _MONTH_K.fullmatch(t):
        return _build(t, m.group(1), m.group(2), 1, "month", m.group(3))
    if m := _MONTH_YUAN.fullmatch(t):
        return _build(t, m.group(1), m.group(2), 1000, "month", None)
    if m := _DAY.fullmatch(t):
        return _build(t, m.group(1), m.group(2), 1, "day", None)
    if m := _HOUR.fullmatch(t):
        return _build(t, m.group(1), m.group(2), 1, "hour", None)
    return _unknown(t)
