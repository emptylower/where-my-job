# src/where_my_job/store/views.py
"""固定视图的参数化读取。用户输入只能成为绑定参数，不能成为 SQL 片段。调用方负责包读事务。"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from ..errors import InvalidInput, ErrorItem

MAX_PAGE_SIZE = 500
DEFAULT_PAGE_SIZE = 100
RELATED_MAX_PAGE_SIZE = 100

# 列名 -> 类型（text/num/int）。只有这些列可筛选/排序；与 v_jobs 视图列集合一致。
from ..config.columns import V_JOBS_COLUMNS
_OPS = {"": "=", "!=": "!=", ">=": ">=", "<=": "<=", ">": ">", "<": "<"}

@dataclass
class JobQuery:
    filters: dict[str, str] = field(default_factory=dict)   # 键为列名加可选比较符后缀：salary_lo>=、title~
    sort: str = "last_seen_at"
    desc: bool = True
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

def _invalid(message: str, path: str) -> InvalidInput:
    return InvalidInput([ErrorItem("SEMANTIC_INVALID", message, path)])

def _parse_key(key: str) -> tuple[str, str]:
    for op in (">=", "<=", "!=", ">", "<", "~"):
        if key.endswith(op):
            return key[: -len(op)], op
    return key, ""

def _coerce(col: str, typ: str, raw: str):
    if typ == "text":
        return raw
    try:
        value = int(raw) if typ == "int" else float(raw)
    except (TypeError, ValueError, OverflowError):
        raise _invalid(f"{col} 需要数值，得到 {raw!r}", f"$.filter.{col}")
    if isinstance(value, float) and not math.isfinite(value):
        raise _invalid(f"{col} 需要有限数值，得到 {raw!r}", f"$.filter.{col}")
    return value

def like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"

def build_where(filters: dict[str, str], columns: dict[str, str]) -> tuple[str, list]:
    clauses, params = [], []
    for key, raw in filters.items():
        col, op = _parse_key(key)
        if col not in columns:
            raise _invalid(f"不允许的筛选列 {col}", f"$.filter.{col}")
        typ = columns[col]
        if op == "~":
            if typ != "text":
                raise _invalid(f"{col} 不是文本列，不能用 ~", f"$.filter.{col}")
            clauses.append(f'"{col}" LIKE ? ESCAPE \'\\\'')
            params.append(like_pattern(raw))
        else:
            clauses.append(f'"{col}" {_OPS[op]} ?')
            params.append(_coerce(col, typ, raw))
    return (" AND ".join(clauses) if clauses else "1=1"), params

def list_jobs(conn, q: JobQuery) -> tuple[list[dict], int, bool]:
    if q.sort not in V_JOBS_COLUMNS:
        raise _invalid(f"不允许的排序列 {q.sort}", "$.sort")
    if not (1 <= q.page_size <= MAX_PAGE_SIZE) or q.page < 1:
        raise _invalid(f"page_size 须在 1..{MAX_PAGE_SIZE}，page >= 1", "$.page")
    where, params = build_where(q.filters, V_JOBS_COLUMNS)
    total = conn.execute(f"select count(*) from v_jobs where {where}", params).fetchone()[0]
    order = f'"{q.sort}" {"DESC" if q.desc else "ASC"} NULLS LAST, job_id ASC'
    offset = (q.page - 1) * q.page_size
    rows = conn.execute(f"select * from v_jobs where {where} order by {order} limit ? offset ?",
                        params + [q.page_size, offset]).fetchall()
    return [dict(r) for r in rows], total, offset + len(rows) < total

_RELATED = {
    "sightings": ("""select observation_id, run_id, task_id, page, observed_at, observed_at_raw, time_precision,
                     tz_assumption, raw_kind, content_hash,
                     (raw_json is null and raw_pruned_at is not null) as raw_pruned
                     from sightings where job_id=? order by observed_at desc nulls last, observation_id asc""",
                  "select count(*) from sightings where job_id=?"),
    "attrs": ("""select key, value_json, source, based_on_revision, updated_at from job_attrs
                 where job_id=? order by key asc, source asc""",
              "select count(*) from job_attrs where job_id=?"),
    # 子计划 04：取完整 v_evidence 行，只经 store.evidence.public_row 输出（见 _project）。
    "evidence": ("select * from v_evidence where job_id=? order by captured_at desc, evidence_id asc",
                 "select count(*) from v_evidence where job_id=?"),
    "reports": ("""select report_id, bundle_id, profile_revision, report_version, created_at from deepdives
                   where job_id=? order by created_at desc, report_id asc""",
                "select count(*) from deepdives where job_id=?"),
    "applications": ("select application_id, created_at from applications where job_id=? order by created_at asc, application_id asc",
                     "select count(*) from applications where job_id=?"),
}

def _project(name: str, row) -> dict:
    """关联列表逐行投影；证据行只允许经 store.evidence.public_row 输出。"""
    if name == "evidence":
        from . import evidence as ev_repo
        return ev_repo.public_row(row)
    return dict(row)

def job_detail(conn, job_id: str, *, related_page: int = 1, related_page_size: int = RELATED_MAX_PAGE_SIZE) -> dict | None:
    if related_page < 1:
        raise _invalid("related_page 须 >= 1", "$.related_page")
    if not (1 <= related_page_size <= RELATED_MAX_PAGE_SIZE):
        raise _invalid(f"related_page_size 须在 1..{RELATED_MAX_PAGE_SIZE}", "$.related_page_size")
    job = conn.execute("select * from v_jobs where job_id=?", (job_id,)).fetchone()
    if job is None:
        return None
    out: dict = {"job": dict(job)}
    offset = (related_page - 1) * related_page_size
    for name, (rows_sql, count_sql) in _RELATED.items():
        total = conn.execute(count_sql, (job_id,)).fetchone()[0]
        rows = conn.execute(rows_sql + " limit ? offset ?", (job_id, related_page_size, offset)).fetchall()
        out[name] = {"items": [_project(name, r) for r in rows], "total": total, "page": related_page,
                     "page_size": related_page_size, "truncated": offset + len(rows) < total}
    return out
