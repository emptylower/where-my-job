# src/where_my_job/normalize/legacy_20260914.py
from __future__ import annotations
import re
from dataclasses import replace
from .fact import Fact
from .legacy import map_legacy_record

def _legacy_tags(tags: str) -> tuple[str, str]:
    exp, degree = "未知", "未知"
    for segment in re.split(r"[|·]", tags):
        token = segment.strip()
        if re.match(r"^(经验不限|应届生|在校生|在校/应届|\d+年以内|1-3年|3-5年|5-10年|10年以上|\d+年以上|3年及以下|3年以内)$", token):
            exp = token
        elif token in ("博士", "硕士", "研究生", "本科", "大专", "中专/中技", "高中", "初中及以下", "学历不限", "初中", "不限"):
            degree = token
    return exp, degree

def fact_for_replay(record: dict, source_name: str) -> Fact:
    """仅用于冻结评分快照，不写回标准 sightings.fact_json。"""
    base = map_legacy_record(record).fact
    exp, degree = _legacy_tags(record.get("tags") or "")
    salary = re.match(r"(\d+)-(\d+)K", record.get("salary") or "")
    return replace(base, city=source_name[:-5].split("_", 1)[0], exp=exp, degree=degree,
        skills=(record.get("skills") or "",), company_industry=record.get("company_industry") or "",
        company_scale=record.get("company_scale") or "", title=record.get("title") or "",
        salary_lo=float(salary.group(1)) if salary else 0.0,
        salary_hi=float(salary.group(2)) if salary else 0.0)
