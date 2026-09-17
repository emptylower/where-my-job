# src/where_my_job/rules/fields.py
"""可用于规则的事实字段白名单。未注册字段不可引用；私有字段永不注册。"""
from __future__ import annotations
from ..normalize.fact import Fact

FIELDS: dict[str, str] = {
    "title": "text", "company_name": "text", "city": "text", "district": "text", "salary_text": "text",
    "salary_lo": "num", "salary_hi": "num", "salary_currency": "text", "salary_period": "text",
    "pay_months": "int", "exp": "text", "degree": "text", "skills": "list", "job_labels": "list",
    "welfare": "list", "company_scale": "text", "company_stage": "text", "company_industry": "text",
    "boss_title": "text", "boss_active_status": "text",
    # 派生文本：固定顺序空格拼接；任一成分缺失时跳过该成分，全部缺失为 None
    "title_skills": "text", "title_skills_industry": "text",
}
DERIVED = {
    "title_skills": ("title", "skills"),
    "title_skills_industry": ("title", "skills", "company_industry"),
}

def derived_text(fact: Fact, name: str) -> str | None:
    parts: list[str] = []
    for src in DERIVED[name]:
        v = getattr(fact, src)
        if v is None or v == () or v == "":
            continue
        parts.append(" ".join(v) if isinstance(v, tuple) else str(v))
    return " ".join(parts) if parts else None

def get_value(fact: Fact, name: str):
    if name in DERIVED:
        return derived_text(fact, name)
    v = getattr(fact, name)
    if v == () or v == "":
        return None
    return v
