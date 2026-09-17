# src/where_my_job/panel/render.py
"""纯渲染：输入已取好的行与元数据，输出自包含 HTML。文本与属性按各自上下文转义；链接白名单；无外部资源。
模板只做一次 re.sub 替换，已插入的业务文本不会被再次扫描。"""
from __future__ import annotations
import html, json, re
from dataclasses import dataclass, field
from importlib import resources
from urllib.parse import urlsplit, urlunsplit
from ..config.columns import V_JOBS_COLUMNS
from .timeline import render_section, TIMELINE_TAB_BUTTON

COLUMN_LABELS = {
    "tier": "档", "score": "分数", "rule_score": "规则分", "dir": "方向", "title": "岗位", "company_name": "公司",
    "city": "城市", "district": "区", "salary_text": "薪资", "salary_lo": "薪资下限(K)", "salary_hi": "薪资上限(K)",
    "exp": "经验", "degree": "学历", "first_seen_at": "首次观察", "last_seen_at": "最近观察", "hit_count": "命中次数",
    "seen_run_count": "观察批次", "match_state": "匹配状态", "report_state": "报告状态", "priority": "优先级",
    "excluded": "已排除", "application_state": "投递状态", "followup_due": "待跟进", "job_id": "ID", "legacy_job_id": "旧ID",
    "skills_json": "技能", "unknowns_json": "待核实", "reasons_json": "理由", "exclusion_reasons_json": "排除原因",
    "job_url": "链接", "company_id": "公司ID", "salary_currency": "币种", "salary_period": "薪资周期", "pay_months": "薪数",
    "fact_revision": "事实版本", "match_run_id": "匹配批次", "score_adjustment": "人工调整", "current_bundle_id": "证据包",
    "report_id": "报告", "application_id": "投递", "view_schema_version": "视图版本",
}
CHART_LABELS = {"dir": "方向分布", "tier": "档位分布", "city": "城市分布", "exp": "经验要求", "degree": "学历要求",
                "report_state": "报告状态", "application_state": "投递状态"}
FILTER_COLUMNS = ("dir", "tier", "city", "exp", "degree", "match_state", "report_state", "application_state")
EXCLUDED_COLUMNS = ("title", "company_name", "city", "exp", "degree", "dir", "exclusion_reasons_json")
UNKNOWN_COLUMNS = ("title", "company_name", "city", "match_state", "unknowns_json")
_CLAMP_COLS = {"title", "company_name", "skills_json", "unknowns_json"}
_NOWRAP_COLS = {"dir", "city", "exp", "degree", "report_state", "application_state", "match_state", "job_url"}
_CLAMP_MULTI_COLS = {"reasons_json", "exclusion_reasons_json"}
_SAFE_PATH = re.compile(r"/(job_detail|gongsi)/[A-Za-z0-9~_-]{1,128}\.html")
_MARKER = re.compile(r"\{\{([A-Z_]+)\}\}")

def esc_text(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)

def esc_attr(s) -> str:
    return html.escape("" if s is None else str(s), quote=True).replace("'", "&#x27;")

def safe_url(u) -> str | None:
    if not isinstance(u, str) or not u:
        return None
    try:
        p = urlsplit(u)
        port = p.port
    except ValueError:
        return None
    if p.scheme != "https" or p.netloc != "www.zhipin.com" or port is not None:
        return None
    if not _SAFE_PATH.fullmatch(p.path):
        return None
    return urlunsplit(("https", "www.zhipin.com", p.path, "", ""))

@dataclass
class PanelSpec:
    title: str
    columns: list[str]
    sort_by: str
    sort_desc: bool
    filters: list[dict]
    charts: list[dict]
    page_size: int
    show_unknown_in_main: bool
    timeline: dict = field(default_factory=lambda: {"enabled": False, "streams": ["applications"]})

    @staticmethod
    def from_dict(d: dict) -> "PanelSpec":
        s = d.get("sort") or {"by": "score", "desc": True}
        tl = d.get("timeline") or {}
        streams = list(dict.fromkeys(tl.get("streams") or ["applications"]))
        return PanelSpec(title=d.get("title", "岗位面板"), columns=list(d["columns"]), sort_by=s["by"], sort_desc=s.get("desc", True),
                         filters=list(d.get("filters") or []), charts=list(d.get("charts") or []),
                         page_size=min(int(d.get("page_size", 500)), 500), show_unknown_in_main=bool(d.get("show_unknown_in_main", True)),
                         timeline={"enabled": bool(tl.get("enabled", False)), "streams": streams})

def _json_list(v) -> list:
    try:
        items = json.loads(v) if isinstance(v, str) else (v or [])
    except ValueError:
        return []
    return items if isinstance(items, list) else []

def _reason_parts(v) -> list[str]:
    parts = []
    for it in _json_list(v):
        if not isinstance(it, dict):
            continue
        d = it.get("delta"); txt = it.get("reason", it.get("rule_id", ""))
        parts.append((f"{d:+g} " if isinstance(d, (int, float)) and not isinstance(d, bool) else "") + str(txt))
    return parts

def _plain(col: str, v) -> str:
    if col in ("skills_json", "unknowns_json"):
        return "、".join(str(x) for x in _json_list(v))
    if col in _CLAMP_MULTI_COLS:
        return "；".join(_reason_parts(v))
    return str(v)

def _cell(col: str, v) -> str:
    if v is None:
        return '<span class="reasons">—</span>'
    if col in ("skills_json", "unknowns_json"):
        return esc_text("、".join(str(x) for x in _json_list(v)))
    if col in ("reasons_json", "exclusion_reasons_json"):
        return '<div class="reasons">' + "<br>".join(esc_text(p) for p in _reason_parts(v)) + "</div>"
    if col in ("score", "rule_score", "score_adjustment", "salary_lo", "salary_hi") and isinstance(v, (int, float)):
        return esc_text(f"{float(v):g}")
    if col == "tier":
        return f'<span class="tier-{esc_attr(v)}">{esc_text(v)}</span>'
    if col == "job_url":                                   # 原始地址占掉整列宽度：只给一个短链接，全文进 title
        u = safe_url(v)
        return f'<a href="{esc_attr(u)}" rel="noopener noreferrer" target="_blank">打开 &#8599;</a>' if u else "—"
    return esc_text(v)

def _cells(cols, r: dict) -> str:
    tds = []
    for c in cols:
        v = r.get(c)
        inner = _cell(c, v)
        classes = []
        if V_JOBS_COLUMNS.get(c) in ("num", "int"):
            classes.append("num")
        if c in _CLAMP_COLS:
            classes.append("clamp")
        elif c in _CLAMP_MULTI_COLS:
            classes.append("clamp-multi")
        if c in _NOWRAP_COLS:                              # 中文不该从词中间折行
            classes.append("nowrap")
        cls = f' class="{" ".join(classes)}"' if classes else ""
        title = f' title="{esc_attr(_plain(c, v))}"' if (c in _CLAMP_COLS or c in _CLAMP_MULTI_COLS) and v is not None else ""
        if c == "title":
            u = safe_url(r.get("job_url"))
            tds.append(f'<td{cls}{title}><a href="{esc_attr(u)}" rel="noopener noreferrer" target="_blank">{inner}</a></td>' if u else f"<td{cls}{title}>{inner}</td>")
        else:
            tds.append(f"<td{cls}{title}>{inner}</td>")
    return "".join(tds)

def _bar_chart(by: str, rows: list[dict]) -> str:
    counts: dict[str, int] = {}
    for r in rows:
        k = r.get(by); k = "未知" if k is None else str(k)
        counts[k] = counts.get(k, 0) + 1
    if not counts:
        return ""
    mx = max(counts.values())
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    bars = "".join(f'<div class="bar"><span style="width:96px;display:inline-block">{esc_text(k)}</span>'
                   f'<i style="width:{int(140 * n / mx)}px"></i><span>{n}</span></div>' for k, n in items)
    return f'<div class="chart"><h2>{esc_text(CHART_LABELS.get(by, by))}</h2>{bars}</div>'

def _group_table(group: dict, cols, note: str) -> str:
    out = [f'<p class="note">{esc_text(note)}</p>']
    if group.get("truncated"):
        out.append(f'<p class="note">显示 {esc_text(group.get("shown"))} / {esc_text(group.get("total"))}</p>')
    rows = group.get("rows") or []
    if not rows:
        out.append('<p class="note">无</p>')
        return "".join(out)
    head = "".join(f"<th>{esc_text(COLUMN_LABELS.get(c, c))}</th>" for c in cols)
    body = "".join(f"<tr>{_cells(cols, r)}</tr>" for r in rows)
    out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
    return "".join(out)

def render_html(spec: PanelSpec, rows: list[dict], meta: dict, *, timeline_rows: list[dict] | None = None,
                timeline_meta: list[dict] | None = None) -> str:
    tpl = resources.files("where_my_job.panel").joinpath("template.html").read_text(encoding="utf-8")
    js = resources.files("where_my_job.panel").joinpath("filter.js").read_text(encoding="utf-8")
    if "</script" in js.lower() or "{{" in js:
        raise AssertionError("固定筛选脚本含非法片段")
    cols = [c for c in spec.columns if c in V_JOBS_COLUMNS]
    thead = "".join(f'<th data-col="{esc_attr(c)}" data-numeric="{1 if V_JOBS_COLUMNS[c] != "text" else 0}">{esc_text(COLUMN_LABELS.get(c, c))}</th>' for c in cols)
    body = []
    for r in rows:
        attrs = [f'data-col-{fc}="{esc_attr("" if r.get(fc) is None else r.get(fc))}"' for fc in FILTER_COLUMNS]
        attrs += [f'data-col-{c}="{esc_attr("" if r.get(c) is None else r.get(c))}"' for c in cols if c not in FILTER_COLUMNS]
        hay = " ".join(str(r.get(k) or "") for k in ("title", "company_name", "city", "skills_json", "dir"))
        attrs.append(f'data-search="{esc_attr(hay)}"')
        body.append(f'<tr {" ".join(attrs)}>{_cells(cols, r)}</tr>')
    filters = []
    for fc in FILTER_COLUMNS:
        vals = sorted({str(r.get(fc)) for r in rows if r.get(fc) is not None})
        if not vals:
            continue
        opts = "".join(f'<option value="{esc_attr(v)}">{esc_text(v)}</option>' for v in vals)
        filters.append(f'<label>{esc_text(COLUMN_LABELS.get(fc, fc))} <select data-filter="{esc_attr(fc)}"><option value="">全部</option>{opts}</select></label>')
    filters.append('<label>搜索 <input data-search type="search" placeholder="岗位/公司/城市/技能"></label>')
    filters.append('<label>可见 <b data-visible-count>0</b> / ' + esc_text(len(rows)) + "</label>")
    charts = "".join(_bar_chart(c["by"], rows) for c in spec.charts if c.get("type") == "bar")
    groups = meta.get("groups") or {}
    main_g = groups.get("main") or {"total": len(rows), "shown": len(rows), "truncated": False}
    empty = {"rows": [], "total": 0, "shown": 0, "truncated": False}
    exc_g = groups.get("excluded") or empty
    unk_g = groups.get("unknown") or empty
    meta_html = "".join(f"<span>{esc_text(k)}：{esc_text(v)}</span>" for k, v in (
        ("as_of", meta.get("as_of")), ("匹配批次", meta.get("match_run_id") or "尚未匹配"),
        ("输入选择", meta.get("input_selection") or "latest"), ("校园岗位", meta.get("campus")),
        ("主列表", f"{main_g.get('shown')} / {main_g.get('total')}"), ("未匹配", meta.get("unmatched", 0)),
        ("截断", "是" if main_g.get("truncated") else "否")))
    warns = "".join(f'<div class="warn">{esc_text(w)}</div>' for w in meta.get("warnings", []))
    tab_defs = [("main", "主列表", main_g), ("excluded", "已排除", exc_g), ("unknown", "待核实", unk_g)]
    group_tabs_html = "".join(f'<button type="button" data-tab-target="{esc_attr(k)}">{esc_text(label)}（{esc_text(g.get("shown"))}/{esc_text(g.get("total"))}）</button>'
                         for k, label, g in tab_defs)
    if timeline_rows is not None:
        group_tabs_html = group_tabs_html + TIMELINE_TAB_BUTTON
        timeline_html = render_section(timeline_rows, timeline_meta or [])
    else:
        timeline_html = ""
    values = {"TITLE": esc_text(spec.title), "META": meta_html, "WARNINGS": warns,
              "CHARTS": charts, "FILTERS": "".join(filters), "THEAD": thead,
              "TBODY": "".join(body), "FILTER_JS": js,
              "TIMELINE": timeline_html, "GROUP_TABS": group_tabs_html,
              "EXCLUDED": _group_table(exc_g, EXCLUDED_COLUMNS, "已排除岗位按排除规则或校园政策排除，仍保留在数据库中，可复核原因"),
              "UNKNOWN": _group_table(unk_g, UNKNOWN_COLUMNS, "以下岗位有缺失或未识别字段，结论待核实")}
    return _MARKER.sub(lambda m: values[m.group(1)], tpl)
