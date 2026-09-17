# src/where_my_job/service/panel.py
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
from ..config.loader import load_json_file
from ..ids import sha256_text
from ..panel.render import render_html, PanelSpec
from ..paths import atomic_write_text, check_export_target, register_managed_output
from ..store import db, matches, panel_queries
from .bootstrap import with_context
from .context import Context
from .panel_timeline import read_timeline
from .staleness import FROZEN_NOTICE, add_warning, version_warnings

DEFAULT_SPEC = {"schema_version": 1, "title": "岗位面板",
                "columns": ["tier", "score", "dir", "title", "company_name", "city", "salary_text", "exp", "degree", "last_seen_at", "report_state"],
                "sort": {"by": "score", "desc": True}, "filters": [],
                "charts": [{"type": "bar", "by": "dir"}, {"type": "bar", "by": "tier"}], "page_size": 500, "show_unknown_in_main": True}

def _campus_text(cfg: dict | None) -> str:
    if not cfg:
        return "未匹配"
    c = cfg.get("campus") or {}
    return ("已包含" if c.get("value") == "include" else "已排除") + ("（用户显式设置）" if c.get("basis") == "explicit" else "（由经验范围推导）")

def run(ctx: Context, spec_path: str | None, out: str | None, open_after: bool) -> dict:
    if spec_path:
        spec_d = load_json_file(Path(spec_path).expanduser().resolve(), "panel")
    elif ctx.home.config("panel.json").exists():
        spec_d = load_json_file(ctx.home.config("panel.json"), "panel")
    else:
        spec_d = DEFAULT_SPEC
    spec = PanelSpec.from_dict(spec_d)
    target = Path(out).expanduser() if out else ctx.home.panel_latest
    if out:
        check_export_target(target, ctx.home)
    run_cfg = version_warnings(ctx)
    filters = {f["column"] + ("" if f["op"] == "=" else f["op"]): str(f["value"]) for f in spec.filters}
    limit = min(spec.page_size, panel_queries.GROUP_LIMIT)
    with db.read_tx(ctx.conn):
        main = panel_queries.fetch_group(ctx.conn, "main", filters=filters, sort=spec.sort_by, desc=spec.sort_desc,
                                         limit=limit, show_unknown_in_main=spec.show_unknown_in_main)
        excluded = panel_queries.fetch_group(ctx.conn, "excluded", filters={}, sort=spec.sort_by, desc=spec.sort_desc,
                                             limit=panel_queries.GROUP_LIMIT)
        unknown = panel_queries.fetch_group(ctx.conn, "unknown", filters={}, sort=spec.sort_by, desc=spec.sort_desc,
                                            limit=panel_queries.GROUP_LIMIT)
        unmatched = panel_queries.count_unmatched(ctx.conn)
        cur = matches.current_run(ctx.conn)
        as_of = ctx.conn.execute("select wmj_as_of()").fetchone()[0]
        timeline_rows, timeline_meta, timeline_warnings = read_timeline(ctx.conn, spec_d)
    ctx.warnings.extend(timeline_warnings)
    if cur is None:
        add_warning(ctx, "尚未匹配：面板只显示事实列，运行 match 后再生成")
    elif (run_cfg or {}).get("input_selection") == "legacy-20260914":
        add_warning(ctx, FROZEN_NOTICE)
    for name, g in (("主列表", main), ("已排除", excluded), ("待核实", unknown)):
        if g["truncated"]:
            add_warning(ctx, f"{name}被截断：显示 {g['shown']} / {g['total']}")
    counts = {k: {"total": g["total"], "shown": g["shown"], "truncated": g["truncated"]}
              for k, g in (("main", main), ("excluded", excluded), ("unknown", unknown))}
    meta = {"as_of": as_of, "match_run_id": cur["run_id"] if cur else None, "campus": _campus_text(run_cfg),
            "input_selection": (run_cfg or {}).get("input_selection"), "warnings": list(ctx.warnings), "unmatched": unmatched,
            "groups": {"main": counts["main"], "excluded": excluded, "unknown": unknown}}
    html = render_html(spec, main["rows"], meta, timeline_rows=timeline_rows, timeline_meta=timeline_meta)
    atomic_write_text(target, html, lay=ctx.home)
    register_managed_output(ctx.home, target, sha256_text(html))
    if open_after and sys.platform == "darwin":
        subprocess.Popen(["open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"out": str(target), "rows": main["shown"], "total": main["total"], "truncated": main["truncated"],
            "groups": counts, "unmatched": unmatched, "match_run_id": cur["run_id"] if cur else None,
            "input_selection": (run_cfg or {}).get("input_selection")}

def register(sub, set_handler):
    p = sub.add_parser("panel", help="生成自包含本地 HTML 面板")
    p.add_argument("--spec"); p.add_argument("--out"); p.add_argument("--open", action="store_true")
    set_handler(p, "panel", lambda ns, w: with_context(ns, w, lambda ctx: run(ctx, ns.spec, ns.out, ns.open)))
