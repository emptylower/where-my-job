# src/where_my_job/adapter/detail.py
"""详情页/公司页解析（纯函数）。JD 走 vendor extract_detail_fields；其余字段只存原文与可严格解析的规范值。
限制页与登录墙已由 BrowserSession 在调用前拦下；选择器与计数正则未经真实环境核验，匹配不到就 unknown。"""
from __future__ import annotations
import json, re
from dataclasses import dataclass, field
from ..vendor.boss_zhipin_scraper.primitives import extract_detail_fields, DetailExtractionError

PARSER_VERSION = "detail-v2.1"
MAX_FULL_TEXT = 12000
# 平台把数字写在标签前面，且两个数连写在页头一行：`1129在招职位236位BOSS`。
# 两个数一起锚定：既不会把 BOSS 数当成岗位数，也挡住页面别处"查看全部N个职位"之类的旁证。
# 匹配不上就两个都记 unknown——宁可没有，也不要错值。
_HEADER_COUNTS = re.compile(r"([0-9][0-9,]*)\s*在招职位\s*([0-9][0-9,]*)\s*位\s*BOSS")

@dataclass
class DetailParse:
    completeness: str                 # complete | partial | unparsed
    jd: str | None
    full_text: str | None
    structured: dict = field(default_factory=dict)
    unknowns: list[str] = field(default_factory=list)

def _ld_fields(ldjson) -> dict:
    out = {"ld_upDate_raw": None, "ld_datePosted_raw": None}
    for raw in ldjson or []:
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            continue
        for o in (obj if isinstance(obj, list) else [obj]):
            if not isinstance(o, dict):
                continue
            if out["ld_upDate_raw"] is None and isinstance(o.get("upDate"), str):
                out["ld_upDate_raw"] = o["upDate"][:64]
            if out["ld_datePosted_raw"] is None and isinstance(o.get("datePosted"), str):
                out["ld_datePosted_raw"] = o["datePosted"][:64]
    out["ld_json_upDate"] = out["ld_upDate_raw"]           # 同一声明值，只展示，不当发布日期
    return out

def _strict_count(raw: str | None) -> int | None:
    """千分位逗号只是写法不是数值：去掉之后仍须是纯数字才收。
    捕获允许逗号而这里不允许，是子计划 19 修掉的口径不一致。"""
    bare = raw.replace(",", "") if raw is not None else None
    return int(bare) if bare is not None and re.fullmatch(r"\d{1,6}", bare) else None

def parse_job_detail(extracted: dict) -> DetailParse:
    page_text = str(extracted.get("page_text") or "")[:MAX_FULL_TEXT]
    ld = _ld_fields(extracted.get("ldjson"))
    structured = {"tags": [t[:200] for t in (extracted.get("tags") or []) if isinstance(t, str)][:64],
                  "boss_active_status": None, **ld}
    unknowns = [k for k in ("ld_upDate_raw", "ld_datePosted_raw") if ld[k] is None]
    try:
        fields = extract_detail_fields({"jd": extracted.get("jd") or "", "page_text": page_text})
    except DetailExtractionError:
        return DetailParse("unparsed", None, page_text or None, structured, unknowns + ["jd"])
    structured["boss_active_status"] = fields.get("boss_active_status") or None
    if structured["boss_active_status"] is None:
        unknowns.append("boss_active_status")
    completeness = "complete"
    if extracted.get("text_truncated") is True:
        completeness = "partial"
        unknowns.append("text_truncated")
    return DetailParse(completeness, fields["jd"], page_text or fields["jd"], structured, unknowns)

def parse_company_page(extracted: dict) -> DetailParse:
    text = str(extracted.get("page_text") or "")[:MAX_FULL_TEXT]
    ld = _ld_fields(extracted.get("ldjson"))
    m = _HEADER_COUNTS.search(text)
    structured = {"job_count_raw": m.group(1) if m else None, "boss_count_raw": m.group(2) if m else None,
                  "ld_upDate_raw": ld["ld_upDate_raw"], "ld_json_upDate": ld["ld_json_upDate"]}
    structured["job_count"] = _strict_count(structured["job_count_raw"])
    structured["boss_count"] = _strict_count(structured["boss_count_raw"])
    unknowns = [k for k in ("job_count", "boss_count") if structured[k] is None]
    if not text:
        return DetailParse("unparsed", None, None, structured, unknowns + ["page_text"])
    completeness = "complete"
    if extracted.get("text_truncated") is True:      # 两个计数是附属信息：缺了记进 unknowns，
        completeness = "partial"                     # 但只有正文截断才把整份公司页证据降级
        unknowns.append("text_truncated")
    return DetailParse(completeness, None, text, structured, unknowns)
