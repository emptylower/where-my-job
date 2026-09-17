"""旧列表文件（上游 map_api_job 输出形态）→ 标准 Fact + 私有 raw。"""
from __future__ import annotations
import re
from dataclasses import dataclass
from .fact import Fact
from .tags import parse_tags
from .salary import parse_salary
from .location import parse_location
from .skills import split_list

PRIVATE_KEYS = ("security_id", "lid", "encrypt_boss_id")
_TEXT_FIELDS = (
    "encrypt_job_id", "encrypt_brand_id", "job_id", "job_link", "company_link",
    "title", "boss_name", "tags", "salary", "location", "skills", "job_labels",
    "welfare", "company_scale", "company_stage", "company_industry",
    "boss_title", "boss_active_status",
)
_SOURCE_ID = re.compile(r"[A-Za-z0-9~_-]{1,128}")
_JOB_LINK = re.compile(r"https://www\.zhipin\.com/job_detail/([A-Za-z0-9~_-]+)\.html")
_COMPANY_LINK = re.compile(r"https://www\.zhipin\.com/gongsi/([A-Za-z0-9~_-]+)\.html")

class LegacyRecordError(ValueError):
    pass

@dataclass(frozen=True)
class MappedLegacy:
    job_id: str
    source_job_id: str
    legacy_job_id: str | None
    company_id: str | None
    company_name: str | None
    fact: Fact
    raw_private: dict          # 完整原记录（含私有字段），只进 sightings.raw_json

def map_legacy_record(rec: dict) -> MappedLegacy:
    if not isinstance(rec, dict):
        raise LegacyRecordError("record is not an object")
    for key in _TEXT_FIELDS:
        if rec.get(key) is not None and not isinstance(rec[key], str):
            raise LegacyRecordError(f"{key} must be text or null")
    enc = (rec.get("encrypt_job_id") or "").strip()
    if not _SOURCE_ID.fullmatch(enc):
        raise LegacyRecordError("missing or invalid encrypt_job_id")
    link = rec.get("job_link") or ""
    m = _JOB_LINK.fullmatch(link)
    if link and (m is None or m.group(1) != enc):
        raise LegacyRecordError("job_link does not match encrypt_job_id")
    brand = (rec.get("encrypt_brand_id") or "").strip()
    if brand and not _SOURCE_ID.fullmatch(brand):
        raise LegacyRecordError("invalid encrypt_brand_id")
    company_link = rec.get("company_link") or ""
    cm = _COMPANY_LINK.fullmatch(company_link)
    if brand and company_link and (cm is None or cm.group(1) != brand):
        raise LegacyRecordError("company_link does not match encrypt_brand_id")
    company_id = f"boss:{brand}" if brand else None
    exp, deg = parse_tags(rec.get("tags"), legacy=False)
    sal = parse_salary(rec.get("salary"))
    city, district = parse_location(rec.get("location"))
    skills = split_list(rec.get("skills"))
    monthly = sal.currency == "CNY" and sal.period == "month"
    salary_lo = sal.lo if monthly else None
    salary_hi = sal.hi if monthly else None
    unknowns: list[str] = []
    if not skills:
        unknowns.append("skills")
    if sal.period is None:
        unknowns.append("salary")
    if salary_lo is None:
        unknowns.append("salary_lo")
    if salary_hi is None:
        unknowns.append("salary_hi")
    if exp is None:
        unknowns.append("exp")
    if deg is None:
        unknowns.append("degree")
    fact = Fact(
        title=(rec.get("title") or None), company_name=(rec.get("boss_name") or None),
        city=city, district=district,
        salary_text=sal.text, salary_lo=salary_lo, salary_hi=salary_hi,
        salary_currency=sal.currency, salary_period=sal.period, pay_months=sal.pay_months,
        exp=exp, degree=deg, skills=skills,
        job_labels=split_list(rec.get("job_labels")), welfare=split_list(rec.get("welfare")),
        company_scale=(rec.get("company_scale") or None), company_stage=(rec.get("company_stage") or None),
        company_industry=(rec.get("company_industry") or None),
        boss_title=(rec.get("boss_title") or None), boss_active_status=(rec.get("boss_active_status") or None),
        unknowns=tuple(unknowns),
    )
    return MappedLegacy(job_id=f"boss:{enc}", source_job_id=enc, legacy_job_id=(rec.get("job_id") or None),
                        company_id=company_id, company_name=(rec.get("boss_name") or None),
                        fact=fact, raw_private=dict(rec))
