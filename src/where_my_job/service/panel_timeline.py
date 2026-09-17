# src/where_my_job/service/panel_timeline.py
"""面板时间线取数。必须在 service.panel.run 读取主列表/已排除/待核实三组的同一个 read_tx 内调用；不渲染 HTML。"""
from __future__ import annotations
from ..store import events as events_store, streams as streams_store

PANEL_TIMELINE_LIMIT = events_store.TIMELINE_MAX_LIMIT

def read_timeline(conn, spec_d: dict) -> tuple[list[dict] | None, list[dict], list[str]]:
    """返回 (rows, meta, warnings)。未启用时 rows 为 None，表示面板不含时间线 tab。"""
    cfg = spec_d.get("timeline") or {}
    if not cfg.get("enabled", False):
        return None, [], []
    names = list(dict.fromkeys(cfg.get("streams") or ["applications"]))
    rows: list[dict] = []
    meta: list[dict] = []
    warnings: list[str] = []
    for name in names:
        if not streams_store.list_revisions(conn, name):
            meta.append({"stream": name, "registered": False, "total": 0, "shown": 0, "truncated": False})
            warnings.append(f"时间线流 {name} 未注册，显示为空表")
            continue
        page = events_store.timeline_page(conn, name, limit=PANEL_TIMELINE_LIMIT)
        rows.extend(page["items"])
        meta.append({"stream": name, "registered": True, "total": page["total"], "shown": len(page["items"]),
                     "truncated": page["truncated"]})
        if page["truncated"]:
            warnings.append(f"时间线流 {name} 被截断：显示 {len(page['items'])} / {page['total']}")
    rows.sort(key=lambda e: (e["occurred_at"], e["recorded_at"], e["root_event_id"]))
    return rows, meta, warnings
