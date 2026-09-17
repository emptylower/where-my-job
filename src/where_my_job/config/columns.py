"""v_jobs 公开列与类型（text/num/int）。validate 与 store 共用的只读常量。"""
from __future__ import annotations

V_JOBS_COLUMNS: dict[str, str] = {
    "job_id": "text", "legacy_job_id": "text", "title": "text", "job_url": "text", "company_id": "text",
    "company_name": "text", "city": "text", "district": "text", "salary_text": "text",
    "salary_lo": "num", "salary_hi": "num", "salary_currency": "text", "salary_period": "text",
    "pay_months": "int", "exp": "text", "degree": "text", "skills_json": "text", "fact_revision": "text",
    "first_seen_at": "text", "last_seen_at": "text", "seen_run_count": "int", "hit_count": "int",
    "match_run_id": "text", "dir": "text", "match_state": "text", "rule_score": "num",
    "score_adjustment": "num", "score": "num", "tier": "text", "reasons_json": "text", "excluded": "int",
    "exclusion_reasons_json": "text", "unknowns_json": "text", "priority": "text",
    "current_bundle_id": "text", "report_id": "text", "report_state": "text",
    "application_id": "text", "application_state": "text", "followup_due": "int",
}
