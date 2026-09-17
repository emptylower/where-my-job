from __future__ import annotations
from dataclasses import dataclass, asdict
from ..ids import sha256_json

FACT_SCHEMA_VERSION = 1
_TUPLE_FIELDS = ("skills", "job_labels", "welfare", "unknowns")

@dataclass(frozen=True)
class Fact:
    title: str | None
    company_name: str | None
    city: str | None
    district: str | None
    salary_text: str | None
    salary_lo: float | None          # 仅明确人民币月薪，千元
    salary_hi: float | None
    salary_currency: str | None      # "CNY" | None
    salary_period: str | None        # "month" | "day" | "hour" | "year" | None
    pay_months: int | None
    exp: str | None
    degree: str | None
    skills: tuple[str, ...]
    job_labels: tuple[str, ...]
    welfare: tuple[str, ...]
    company_scale: str | None
    company_stage: str | None
    company_industry: str | None
    boss_title: str | None
    boss_active_status: str | None
    unknowns: tuple[str, ...]

    def to_json(self) -> dict:
        d = asdict(self)
        d["fact_schema_version"] = FACT_SCHEMA_VERSION
        for k in _TUPLE_FIELDS:
            d[k] = list(d[k])
        return d

    @staticmethod
    def from_json(d: dict) -> "Fact":
        d = dict(d)
        d.pop("fact_schema_version", None)
        for k in _TUPLE_FIELDS:
            d[k] = tuple(d.get(k) or ())
        return Fact(**d)

def fact_hash(f: Fact) -> str:
    return sha256_json(f.to_json())
