# src/where_my_job/rules/skills.py
from __future__ import annotations
import re

def normalize_skill(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip()).lower()

def count_hits(text: str | None, categories: dict[str, str], *, flags_i: bool) -> tuple[list[str], int]:
    """按类别顺序返回命中的类别名与去重数。每类最多计 1。"""
    if not text:
        return [], 0
    hits = []
    for name, pattern in categories.items():
        if re.search(pattern, text, re.IGNORECASE if flags_i else 0):
            hits.append(name)
    return hits, len(hits)
