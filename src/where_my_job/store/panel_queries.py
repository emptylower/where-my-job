# src/where_my_job/store/panel_queries.py
"""面板三组固定查询：主列表 / 已排除 / 待核实。用户筛选只进主列表；全部参数化绑定。调用方持有 read_tx。"""
from __future__ import annotations
from ..config.columns import V_JOBS_COLUMNS
from ..errors import InvalidInput, ErrorItem
from .db import Connection
from .views import build_where

GROUP_LIMIT = 500
GROUPS = ("main", "excluded", "unknown")

def fetch_group(conn: Connection, group: str, *, filters: dict[str, str], sort: str, desc: bool, limit: int,
                show_unknown_in_main: bool = True) -> dict:
    if group not in GROUPS:
        raise ValueError(f"unknown panel group {group}")
    if sort not in V_JOBS_COLUMNS:
        raise InvalidInput([ErrorItem("SEMANTIC_INVALID", f"不允许的排序列 {sort}", "$.sort.by")])
    if not 1 <= limit <= GROUP_LIMIT:
        raise InvalidInput([ErrorItem("SEMANTIC_INVALID", f"每组行数须在 1..{GROUP_LIMIT}", "$.page_size")])
    if group == "main":
        where, bound = build_where(filters, V_JOBS_COLUMNS)
        clauses, params = [where, "excluded IS NULL OR excluded != ?"], list(bound) + [1]
        if not show_unknown_in_main:
            clauses.append("json_array_length(unknowns_json) = 0")
    elif group == "excluded":
        clauses, params = ["excluded = ?"], [1]
    else:
        clauses, params = ["excluded IS NULL OR excluded != ?", "json_array_length(unknowns_json) > 0"], [1]
    where_sql = " AND ".join(f"({c})" for c in clauses)
    total = conn.execute(f"select count(*) from v_jobs where {where_sql}", params).fetchone()[0]
    order = f'"{sort}" {"DESC" if desc else "ASC"} NULLS LAST, job_id ASC'
    rows = [dict(r) for r in conn.execute(f"select * from v_jobs where {where_sql} order by {order} limit ?",
                                          params + [limit]).fetchall()]
    return {"rows": rows, "total": total, "shown": len(rows), "truncated": len(rows) < total}

def count_unmatched(conn: Connection) -> int:
    return conn.execute("select count(*) from v_jobs where match_state = 'missing'").fetchone()[0]
