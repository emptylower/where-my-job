# src/where_my_job/store/signals.py
"""CLI 可计算的招聘信号。只陈述观察事实，不推断发布时间、真假或编制。措辞遵守设计 v3 §7 表。"""
from __future__ import annotations
from ..clock import parse_iso

def _days(first: str, last: str) -> int:
    return (parse_iso(last) - parse_iso(first)).days

def observation_span(*, first: str | None, last: str | None, hits: int, runs: int, as_of: str | None) -> dict:
    base = {"hits": hits, "runs": runs, "first": first, "last": last, "as_of": as_of}
    if not first or not last:
        return dict(base, days=None, statement="本工具尚无可解释的观察时间；无法确认发布日期。")
    days = _days(first, last)
    return dict(base, days=days,
                statement=(f"截至 {(as_of or '读取时刻未知')[:19]}，本工具观察跨度 {days} 天，累计观察 {hits} 次"
                           f"（{runs} 个批次），首末日期 {first[:10]} / {last[:10]}。这是离散观察，"
                           "只反映本工具的搜索条件与覆盖范围，无法确认发布日期，也不能说明是否仍在招聘。"))

def _count(value):
    return value if type(value) is int and value >= 0 else None

def count_ratio(*, boss_count, job_count, boss_count_raw: str | None = None,
                job_count_raw: str | None = None, snapshot_at: str | None = None) -> dict:
    b, j = _count(boss_count), _count(job_count)
    base = {"boss_count": b, "job_count": j, "boss_count_raw": boss_count_raw, "job_count_raw": job_count_raw,
            "snapshot_at": snapshot_at}
    if b is None or j is None or j == 0:
        return dict(base, ratio="unknown", statement="公司页计数缺失、无法解析或岗位数为 0，无法计算比值。")
    return dict(base, ratio=round(b / j, 4),
                statement=(f"公司页展示招聘者 {b} 人、在招岗位 {j} 个（快照 {snapshot_at or '时间未知'}，"
                           "口径未核验）。该比值不能单独说明岗位真实性。"))

_PAIRS = (("salary_text", "detail_salary_text"), ("exp", "detail_exp"), ("degree", "detail_degree"))

def list_detail_diff(fact: dict, detail_structured: dict) -> list[dict]:
    out = []
    for f, d in _PAIRS:
        if detail_structured.get(d) is not None and fact.get(f) is not None and detail_structured[d] != fact.get(f):
            out.append({"field": f, "list": fact.get(f), "detail": detail_structured[d]})
    return out

def up_date_raw(detail_structured: dict) -> dict:
    value = detail_structured.get("ld_json_upDate")
    raw = detail_structured.get("ld_upDate_raw")
    if value:
        statement = f"页面 ld+json upDate 声明值为 {value}（原文 {raw if raw else '未保存'}），语义未核验，无法确认发布日期。"
    else:
        statement = "页面未提供 upDate；无法确认发布日期。"
    return {"value": value, "raw": raw, "statement": statement}
