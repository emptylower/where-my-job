# src/where_my_job/validate/semantic/scoring.py
from __future__ import annotations
from .. import Issue, Facts
from ...rules.eval import compile_scoring, ScoringCompileError
from ...rules.campus import ALL_EXPS

def check(obj: dict, facts: Facts) -> list[Issue]:
    issues: list[Issue] = []
    for i, e in enumerate(obj.get("experience_allowlist") or []):
        if e not in ALL_EXPS:
            issues.append(Issue("SEMANTIC_INVALID", f"$.experience_allowlist[{i}]", f"未知经验枚举 {e}"))
    selection = obj.get("input_selection", "latest")
    legacy_input = obj.get("legacy_input")
    if selection == "legacy-20260914" and legacy_input is None:
        issues.append(Issue("SEMANTIC_INVALID", "$.legacy_input", "legacy-20260914 冻结模式必须给出 legacy_input.files"))
    if selection == "latest" and legacy_input is not None:
        issues.append(Issue("SEMANTIC_INVALID", "$.legacy_input", "latest 模式不得包含 legacy_input"))
    if legacy_input is not None:
        names: set[str] = set(); hashes: set[str] = set()
        for i, f in enumerate(legacy_input["files"]):
            if f["name"] in names:
                issues.append(Issue("SEMANTIC_INVALID", f"$.legacy_input.files[{i}].name", "冻结文件名重复"))
            if f["sha256"] in hashes:
                issues.append(Issue("SEMANTIC_INVALID", f"$.legacy_input.files[{i}].sha256", "冻结文件内容 hash 重复"))
            names.add(f["name"]); hashes.add(f["sha256"])
    if issues:
        return issues
    try:
        compile_scoring(obj)
    except ScoringCompileError as e:
        issues.append(Issue("SEMANTIC_INVALID", e.path, e.message))
    return issues
