"""joblist.json 原始岗位对象 → Fact + 私有 raw。字段名以上游 map_api_job 为准；私有标识只进 raw。"""
from __future__ import annotations
import re
from dataclasses import dataclass
from .fact import Fact
from .tags import parse_tags
from .salary import parse_salary

PRIVATE_KEYS = ("securityId", "lid", "encryptBossId")
_SOURCE_ID = re.compile(r"[A-Za-z0-9~_-]{1,128}")
_TEXT = ("encryptJobId", "encryptBrandId", "jobName", "salaryDesc", "cityName", "areaDistrict", "businessDistrict",
         "jobExperience", "jobDegree", "brandName", "bossTitle", "brandScaleName", "brandStageName", "brandIndustry",
         "activeTimeDesc")
_LISTS = ("skills", "jobLabels", "welfareList")

class ApiEntryError(ValueError):
    pass

@dataclass(frozen=True)
class MappedApi:
    job_id: str
    source_job_id: str
    legacy_job_id: None
    company_id: str | None
    company_name: str | None
    fact: Fact
    raw_private: dict

def _texts(v: list) -> tuple[str, ...]:
    out: list[str] = []
    for x in v:
        s = x.strip()
        if s and s not in out:
            out.append(s)
    return tuple(out)

def map_api_entry(raw) -> MappedApi:
    if not isinstance(raw, dict):
        raise ApiEntryError("entry is not an object")
    for key in _TEXT:
        if raw.get(key) is not None and not isinstance(raw[key], str):
            raise ApiEntryError(f"{key} must be text or null")
    for key in _LISTS:
        v = raw.get(key)
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            raise ApiEntryError(f"{key} must be a list of text")
    enc = (raw.get("encryptJobId") or "").strip()
    if not _SOURCE_ID.fullmatch(enc):
        raise ApiEntryError("missing or invalid encryptJobId")
    brand = (raw.get("encryptBrandId") or "").strip()
    if brand and not _SOURCE_ID.fullmatch(brand):
        raise ApiEntryError("invalid encryptBrandId")
    exp, deg = parse_tags(" | ".join(x for x in (raw.get("jobExperience") or "", raw.get("jobDegree") or "") if x),
                          legacy=False)
    sal = parse_salary(raw.get("salaryDesc"))
    monthly = sal.currency == "CNY" and sal.period == "month"
    salary_lo = sal.lo if monthly else None
    salary_hi = sal.hi if monthly else None
    skills = _texts(raw.get("skills") or [])
    unknowns = []
    if not skills: unknowns.append("skills")
    if sal.period is None: unknowns.append("salary")
    if salary_lo is None: unknowns.append("salary_lo")
    if salary_hi is None: unknowns.append("salary_hi")
    if exp is None: unknowns.append("exp")
    if deg is None: unknowns.append("degree")
    if raw.get("bossOnline") is True:
        boss_status = "在线"
    else:
        boss_status = (raw.get("activeTimeDesc") or "").strip() or None
    fact = Fact(
        title=(raw.get("jobName") or None), company_name=(raw.get("brandName") or None),
        city=(raw.get("cityName") or None), district=(raw.get("areaDistrict") or None),
        salary_text=sal.text, salary_lo=salary_lo, salary_hi=salary_hi, salary_currency=sal.currency,
        salary_period=sal.period, pay_months=sal.pay_months, exp=exp, degree=deg, skills=skills,
        job_labels=_texts(raw.get("jobLabels") or []), welfare=_texts(raw.get("welfareList") or []),
        company_scale=(raw.get("brandScaleName") or None), company_stage=(raw.get("brandStageName") or None),
        company_industry=(raw.get("brandIndustry") or None), boss_title=(raw.get("bossTitle") or None),
        boss_active_status=boss_status, unknowns=tuple(unknowns),
    )
    return MappedApi(job_id=f"boss:{enc}", source_job_id=enc, legacy_job_id=None,
                     company_id=f"boss:{brand}" if brand else None, company_name=(raw.get("brandName") or None),
                     fact=fact, raw_private=dict(raw))
