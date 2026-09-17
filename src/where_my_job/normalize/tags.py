from __future__ import annotations
import re

EXP_STANDARD = ("经验不限", "在校生", "应届生", "在校/应届", "1年以内", "1-3年", "3-5年", "5-10年", "10年以上")
EXP_LEGACY_EXTRA = ("3年以内", "3年及以下")
DEGREE_STANDARD = ("初中及以下", "中专/中技", "高中", "大专", "本科", "硕士", "博士", "学历不限")
DEGREE_SYNONYMS = {"研究生": "硕士", "不限": "学历不限", "初中": "初中及以下"}

def parse_tags(tags: str | None, legacy: bool = False) -> tuple[str | None, str | None]:
    """把 '1-3年 | 本科' 拆成 (exp, degree)。未识别为 None。legacy=True 保留旧经验枚举原文。"""
    exp = deg = None
    for seg in re.split(r"[|·]", tags or ""):
        s = seg.strip()
        if not s:
            continue
        if s in EXP_STANDARD or (legacy and s in EXP_LEGACY_EXTRA):
            exp = exp or s
        elif s in DEGREE_STANDARD:
            deg = deg or s
        elif s in DEGREE_SYNONYMS:
            deg = deg or DEGREE_SYNONYMS[s]
    return exp, deg
