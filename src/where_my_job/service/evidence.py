# src/where_my_job/service/evidence.py
from __future__ import annotations
import os
from pathlib import Path
from ..config.loader import read_json_file, validate_object
from ..errors import InvalidInput, EnvError, ErrorItem
from ..paths import atomic_write_text, check_export_target
from ..store import db, evidence as ev_repo, bundles as bundle_repo
from ..validate import Facts
from .bootstrap import with_context
from .context import Context

def _err(code: str, message: str, path: str) -> InvalidInput:
    return InvalidInput([ErrorItem(code, message, path)])

def facts_for(ctx: Context, job_id: str | None) -> Facts:
    """数据库事实快照（调用方持有事务）。两个 dict 恒非 None，表示已注入。"""
    if job_id and ctx.conn.execute("select 1 from jobs where job_id=?", (job_id,)).fetchone():
        return Facts(job_ids=frozenset({job_id}),
                     evidence_ids_by_job={job_id: ev_repo.ids_for_job(ctx.conn, job_id)},
                     bundle_ids_by_job={job_id: bundle_repo.ids_for_job(ctx.conn, job_id)})
    return Facts(job_ids=frozenset(), evidence_ids_by_job={}, bundle_ids_by_job={})

def add(ctx: Context, job_id: str, file: str, origin: str) -> dict:
    obj = dict(read_json_file(file))
    if obj.get("job_id") is not None and obj["job_id"] != job_id:
        raise _err("SEMANTIC_INVALID", f"文件 job_id={obj['job_id']} 与命令行 {job_id} 不一致", "$.job_id")
    if obj.get("origin") is not None and obj["origin"] != origin:
        raise _err("SEMANTIC_INVALID", f"文件 origin={obj['origin']} 与 --origin {origin} 不一致", "$.origin")
    obj["origin"] = origin
    if obj.get("job_id") is None and obj.get("company_id") is None:
        obj["job_id"] = job_id
    with db.write_tx(ctx.conn):
        if obj.get("job_id") is None:
            row = ctx.conn.execute("select company_id from jobs where job_id=?", (job_id,)).fetchone()
            if row is None:
                raise _err("NOT_FOUND", f"岗位不存在: {job_id}", "$.job_id")
            if row["company_id"] is None or row["company_id"] != obj["company_id"]:
                raise _err("EVIDENCE_REF_INVALID", "company_id 不是该岗位已核实的公司", "$.company_id")
        validate_object("evidence", obj, facts_for(ctx, job_id))
        eid, created = ev_repo.insert_external(ctx.conn, ctx.clock, obj, origin=origin)
        stored = ev_repo.get_public(ctx.conn, eid)
    return {"evidence_id": eid, "created": created, "origin": stored["origin"], "kind": stored["kind"],
            "job_id": stored["job_id"], "company_id": stored["company_id"]}

def list_(ctx: Context, *, job_id, company_id, bundle_id, page: int, page_size: int, limit: int, offset: int) -> dict:
    if bundle_id is not None:
        if job_id is not None or company_id is not None:
            raise _err("SCHEMA_INVALID", "--bundle 与 --job/--company 互斥", "$.bundle")
        with db.read_tx(ctx.conn):
            return bundle_repo.evidence_page(ctx.conn, bundle_id, limit=limit, offset=offset)
    if (job_id is None) == (company_id is None):
        raise _err("SCHEMA_INVALID", "需要且只能给 --job、--company、--bundle 之一", "$.job")
    with db.read_tx(ctx.conn):
        rows, total, truncated = ev_repo.list_public(ctx.conn, job_id=job_id, company_id=company_id,
                                                     page=page, page_size=page_size)
    return {"evidence": rows, "total": total, "page": page, "page_size": page_size, "truncated": truncated}

def show(ctx: Context, evidence_id: str, local_out: str | None) -> dict:
    with db.read_tx(ctx.conn):
        row = ev_repo.get_public(ctx.conn, evidence_id)
        full = ev_repo.get_full_text(ctx.conn, evidence_id) if (row is not None and local_out) else None
    if row is None:
        raise _err("NOT_FOUND", f"证据不存在: {evidence_id}", "$.evidence_id")
    if not local_out:
        return {"evidence": row}
    text, state = full
    if state != "present":
        raise _err("NOT_FOUND", "原文已手动清理，无法写出" if state == "pruned" else "该证据没有保存原文", "$.local_out")
    target = Path(local_out).expanduser()
    check_export_target(target, ctx.home)
    parent = target.parent
    if parent.exists() and not os.access(parent, os.W_OK):
        raise EnvError("PERMISSION_DENIED", f"无法写入目录: {parent}")
    atomic_write_text(target, text, lay=ctx.home)
    return {"evidence_id": evidence_id, "local_out": str(target.resolve()), "full_text_state": state}

def register(sub, set_handler):
    p = sub.add_parser("evidence", help="站外/用户证据的提交与受限读取")
    s = p.add_subparsers(dest="evidence_cmd")
    s.required = True
    a = s.add_parser("add")
    a.add_argument("job_id")
    a.add_argument("--file", required=True)
    a.add_argument("--origin", choices=["agent", "user"], default="agent")
    set_handler(a, "evidence add", lambda ns, w: with_context(ns, w, lambda ctx: add(ctx, ns.job_id, ns.file, ns.origin), write=True))
    l = s.add_parser("list")
    l.add_argument("--job")
    l.add_argument("--company")
    l.add_argument("--bundle")
    l.add_argument("--page", type=int, default=1)
    l.add_argument("--page-size", type=int, default=50)
    l.add_argument("--limit", type=int, default=50)
    l.add_argument("--offset", type=int, default=0)
    set_handler(l, "evidence list", lambda ns, w: with_context(ns, w, lambda ctx: list_(
        ctx, job_id=ns.job, company_id=ns.company, bundle_id=ns.bundle, page=ns.page, page_size=ns.page_size,
        limit=ns.limit, offset=ns.offset)))
    g = s.add_parser("show")
    g.add_argument("evidence_id")
    g.add_argument("--local-out")
    set_handler(g, "evidence show", lambda ns, w: with_context(ns, w, lambda ctx: show(ctx, ns.evidence_id, ns.local_out)))
