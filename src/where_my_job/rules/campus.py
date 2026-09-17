# src/where_my_job/rules/campus.py
"""校园岗位政策：设计 v3 §5（用户决策 2026-09-14）。"""
from __future__ import annotations
from dataclasses import dataclass
from ..config.search_codes import FILTER_TABLES

CODE_TO_EXP = {code: label for label, code in FILTER_TABLES["experience"].items() if code != "0"}
NO_EXPERIENCE_EXPS = {"经验不限", "在校生", "应届生", "在校/应届"}
ALL_EXPS = NO_EXPERIENCE_EXPS | {"1年以内", "1-3年", "3-5年", "5-10年", "10年以上"}

@dataclass(frozen=True)
class CampusDecision:
    value: str          # include | exclude
    basis: str          # explicit | no_experience_filter | union_contains_no_experience | only_year_bands
    inputs: dict

def derive(policy: str, *, strategy_codes: list[str], scoring_allowlist: list[str] | None,
           scoring_exclude_exps: list[str]) -> CampusDecision:
    inputs = {"strategy_codes": list(strategy_codes), "scoring_allowlist": scoring_allowlist,
              "scoring_exclude_exps": list(scoring_exclude_exps)}
    if policy in ("include", "exclude"):
        return CampusDecision(policy, "explicit", inputs)
    allowed: set[str] = set()
    has_filter = False
    codes = [c for c in strategy_codes if c in CODE_TO_EXP]
    if codes:
        has_filter = True
        allowed |= {CODE_TO_EXP[c] for c in codes}
    if scoring_allowlist:
        has_filter = True
        allowed |= set(scoring_allowlist)
    elif scoring_exclude_exps:
        has_filter = True
        allowed |= ALL_EXPS - set(scoring_exclude_exps)
    if not has_filter:
        return CampusDecision("include", "no_experience_filter", inputs)
    if allowed & NO_EXPERIENCE_EXPS:
        return CampusDecision("include", "union_contains_no_experience", inputs)
    return CampusDecision("exclude", "only_year_bands", inputs)

def exclude_exps_from_scoring(cfg: dict) -> list[str]:
    """从 scoring.exclude 里 field=exp 的 in/eq 顶层叶子收集被排除的经验枚举（不解析嵌套）。"""
    out: list[str] = []
    for x in cfg.get("exclude", []):
        w = x.get("when", {})
        if isinstance(w, dict) and w.get("field") == "exp":
            if "in" in w: out.extend(v for v in w["in"] if isinstance(v, str))
            if "eq" in w and isinstance(w["eq"], str): out.append(w["eq"])
    return out
