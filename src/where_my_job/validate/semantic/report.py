# src/where_my_job/validate/semantic/report.py
from __future__ import annotations
import re
from .. import Issue, Facts

CONCLUSIONS = ("倾向真实在招", "倾向长期挂岗", "证据不足")
INSUFFICIENT = "证据不足"
SECTIONS = ("## 招聘信号判断", "## JD 翻译", "## 不匹配点", "## 简历建议")
_RAW_HTML = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
_PERCENT = re.compile(r"\d+(\.\d+)?\s*[%％]|百分之")     # 设计 §7：无校准数据不允许百分比置信度
SIGNAL_SECTION = "## 招聘信号判断"

def _section_text(md: str, heading: str) -> str:
    """取某个二级标题到下一个二级标题之间的正文；标题不存在返回空串。"""
    start = md.find(heading)
    if start < 0:
        return ""
    body = md[start + len(heading):]
    nxt = re.search(r"^## ", body, re.M)
    return body[:nxt.start()] if nxt else body

def _empty_sections(md: str) -> list[str]:
    positions = [(md.find(h), h) for h in SECTIONS]
    missing = [h for p, h in positions if p < 0]
    if missing:
        return missing
    ordered = sorted(positions)
    out = []
    for i, (p, h) in enumerate(ordered):
        end = ordered[i + 1][0] if i + 1 < len(ordered) else len(md)
        if not md[p + len(h):end].strip():
            out.append(h)
    return out

def check(obj: dict, facts: Facts) -> list[Issue]:
    issues: list[Issue] = []
    job_id = obj["job_id"]
    injected = facts.evidence_ids_by_job is not None
    if injected and job_id not in facts.job_ids:
        return [Issue("NOT_FOUND", "$.job_id", f"岗位不存在: {job_id}")]
    allowed = facts.evidence_ids_by_job.get(job_id, frozenset()) if injected else None
    if facts.bundle_ids_by_job is not None and obj["bundle_id"] not in facts.bundle_ids_by_job.get(job_id, frozenset()):
        issues.append(Issue("NOT_FOUND", "$.bundle_id", f"证据包不属于该岗位或不存在: {obj['bundle_id']}"))

    def ref(eid: str, path: str) -> None:
        if allowed is not None and eid not in allowed:
            issues.append(Issue("EVIDENCE_REF_INVALID", path, f"证据不属于该岗位: {eid}"))

    for i, eid in enumerate(obj.get("extra_evidence_ids", [])):
        ref(eid, f"$.extra_evidence_ids[{i}]")
    a = obj["authentic"]
    for arr in ("facts", "supporting", "opposing"):
        for i, item in enumerate(a[arr]):
            ref(item["evidence_id"], f"$.authentic.{arr}[{i}].evidence_id")
    for i, s in enumerate(obj["jd_translation"]["sentences"]):
        if "evidence_id" in s:
            ref(s["evidence_id"], f"$.jd_translation.sentences[{i}].evidence_id")
        if "assumption" in s and not s["assumption"].strip():
            issues.append(Issue("SEMANTIC_INVALID", f"$.jd_translation.sentences[{i}].assumption", "假设不能只含空白"))
        for key in ("original", "explanation", "assumption"):
            if key in s and _RAW_HTML.search(s[key]):
                issues.append(Issue("SEMANTIC_INVALID", f"$.jd_translation.sentences[{i}].{key}", "不允许原始 HTML"))
    for i, m in enumerate(obj["mismatches"]):
        if "evidence_id" in m:
            ref(m["evidence_id"], f"$.mismatches[{i}].evidence_id")
        if "assumption" in m and not m["assumption"].strip():
            issues.append(Issue("SEMANTIC_INVALID", f"$.mismatches[{i}].assumption", "假设不能只含空白"))

    for arr in ("facts", "supporting", "opposing"):
        for i, item in enumerate(a[arr]):
            if _PERCENT.search(item.get("claim") or ""):
                issues.append(Issue("SEMANTIC_INVALID", f"$.authentic.{arr}[{i}].claim",
                                    "招聘信号判断不允许百分比表述（无校准数据）"))
    for i, u in enumerate(a["unknowns"]):
        if isinstance(u, str) and _PERCENT.search(u):
            issues.append(Issue("SEMANTIC_INVALID", f"$.authentic.unknowns[{i}]",
                                "招聘信号判断不允许百分比表述（无校准数据）"))

    sup, opp = a["supporting"], a["opposing"]
    if not sup and not opp and a["conclusion"] != INSUFFICIENT:
        issues.append(Issue("REPORT_INCOMPLETE", "$.authentic.conclusion", "支持与反对信号均为空时结论必须为“证据不足”"))
    elif a["conclusion"] != INSUFFICIENT:
        needed = sup if a["conclusion"] == "倾向真实在招" else opp
        valid = [x for x in needed if allowed is None or x["evidence_id"] in allowed]
        if not valid:
            issues.append(Issue("REPORT_INCOMPLETE", "$.authentic.conclusion",
                                f"结论“{a['conclusion']}”至少需要一条带有效来源的相关信号"))
    if (not sup or not opp) and not a["unknowns"]:
        issues.append(Issue("REPORT_INCOMPLETE", "$.authentic.unknowns", "信号数组为空时必须说明未取得何种线索与判断限制"))
    md = obj["report_md"]
    empty = _empty_sections(md)
    if empty:
        issues.append(Issue("REPORT_INCOMPLETE", "$.report_md", "报告缺少或为空的部分: " + "、".join(empty)))
    if _RAW_HTML.search(md):
        issues.append(Issue("SEMANTIC_INVALID", "$.report_md", "报告 Markdown 不允许原始 HTML 标签"))
    if _PERCENT.search(_section_text(md, SIGNAL_SECTION)):
        issues.append(Issue("SEMANTIC_INVALID", "$.report_md", "“招聘信号判断”部分不允许百分比表述（无校准数据）"))
    return issues
