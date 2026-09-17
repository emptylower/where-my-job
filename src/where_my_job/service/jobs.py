# src/where_my_job/service/jobs.py
from __future__ import annotations
import re
from ..errors import InvalidInput, ErrorItem
from ..store import db, views
from .bootstrap import with_context
from .context import Context
from .staleness import version_warnings

_FILTER_ARG = re.compile(r"^([a-z][a-z0-9_]*)(>=|<=|!=|~=|=|>|<|~)(.*)$", re.S)

def _parse_filters(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for index, item in enumerate(items or []):
        match = _FILTER_ARG.fullmatch(item)
        if match is None:
            raise InvalidInput([ErrorItem("SCHEMA_INVALID", "筛选须为列名、比较符和值", f"$.filter[{index}]")])
        column, op, value = match.groups()
        op = "~" if op == "~=" else op
        key = column + ("" if op == "=" else op)
        if key in out:
            raise InvalidInput([ErrorItem("SEMANTIC_INVALID", "同一筛选列与比较符重复", f"$.filter[{index}]")])
        out[key] = value
    return out

def list_(ctx: Context, ns) -> dict:
    version_warnings(ctx)
    q = views.JobQuery(filters=_parse_filters(ns.filter), sort=ns.sort, desc=ns.desc,
                       page=ns.page, page_size=ns.page_size)
    with db.read_tx(ctx.conn):
        rows, total, truncated = views.list_jobs(ctx.conn, q)
        as_of = ctx.conn.execute("select wmj_as_of()").fetchone()[0]
    return {"jobs": rows, "total": total, "page": q.page, "page_size": q.page_size,
            "truncated": truncated, "as_of": as_of}

def show(ctx: Context, ns) -> dict:
    version_warnings(ctx)
    with db.read_tx(ctx.conn):
        d = views.job_detail(ctx.conn, ns.job_id, related_page=ns.related_page,
                             related_page_size=ns.related_page_size)
    if d is None:
        raise InvalidInput([ErrorItem("NOT_FOUND", f"岗位不存在: {ns.job_id}", "$.job_id")])
    return d

def register(sub, set_handler):
    p = sub.add_parser("job", help="固定字段查询")
    s = p.add_subparsers(dest="job_cmd")
    s.required = True
    l = s.add_parser("list")
    l.add_argument("--filter", action="append", default=[], help="列名+比较符+值；比较符 = != >= <= > < ~")
    l.add_argument("--sort", default="last_seen_at")
    l.add_argument("--desc", action="store_true")
    l.add_argument("--page", type=int, default=1)
    l.add_argument("--page-size", type=int, default=views.DEFAULT_PAGE_SIZE)
    set_handler(l, "job list", lambda ns, w: with_context(ns, w, lambda ctx: list_(ctx, ns)))
    g = s.add_parser("show")
    g.add_argument("job_id")
    g.add_argument("--related-page", type=int, default=1)
    g.add_argument("--related-page-size", type=int, default=views.RELATED_MAX_PAGE_SIZE)
    set_handler(g, "job show", lambda ns, w: with_context(ns, w, lambda ctx: show(ctx, ns)))
