# src/where_my_job/service/reports.py
from __future__ import annotations
from ..config.loader import read_json_file, validate_object
from ..errors import InvalidInput, ErrorItem
from ..store import db, jobs as job_repo, reports as report_repo
from ..validate.schema import schema_issues
from .bootstrap import with_context
from .context import Context
from .evidence import facts_for

def _err(code: str, message: str, path: str) -> InvalidInput:
    return InvalidInput([ErrorItem(code, message, path)])

def set_(ctx: Context, job_id: str, file: str) -> dict:
    obj = read_json_file(file)
    issues = schema_issues("report", obj)
    if issues:
        raise InvalidInput([ErrorItem(i.code, i.message, i.path) for i in issues])
    if obj["job_id"] != job_id:
        raise _err("SEMANTIC_INVALID", f"文件 job_id={obj['job_id']} 与命令行 {job_id} 不一致", "$.job_id")
    with db.write_tx(ctx.conn):
        if not job_repo.exists(ctx.conn, job_id):
            raise _err("NOT_FOUND", f"岗位不存在: {job_id}", "$.job_id")
        if report_repo.find_by_key(ctx.conn, obj["idempotency_key"]) is None:
            validate_object("report", obj, facts_for(ctx, job_id))
        rid, created = report_repo.insert(ctx.conn, ctx.clock, obj)
    with db.read_tx(ctx.conn):
        summary = report_repo.persisted_summary(ctx.conn, rid)
    return dict(summary, created=created)

def get(ctx: Context, job_id: str, report_id: str | None) -> dict:
    with db.read_tx(ctx.conn):
        if not job_repo.exists(ctx.conn, job_id):
            raise _err("NOT_FOUND", f"岗位不存在: {job_id}", "$.job_id")
        r = report_repo.get(ctx.conn, job_id, report_id=report_id)
        if r is None:
            raise _err("NOT_FOUND", "没有报告" if report_id is None else f"报告不存在: {report_id}", "$.report_id")
        r["history"] = report_repo.list_for_job(ctx.conn, job_id)
    return r

def register(sub, set_handler):
    p = sub.add_parser("report", help="结构化报告的原子提交与读取")
    s = p.add_subparsers(dest="report_cmd")
    s.required = True
    a = s.add_parser("set")
    a.add_argument("job_id")
    a.add_argument("--file", required=True)
    set_handler(a, "report set", lambda ns, w: with_context(ns, w, lambda ctx: set_(ctx, ns.job_id, ns.file), write=True))
    g = s.add_parser("get")
    g.add_argument("job_id")
    g.add_argument("--report-id")
    set_handler(g, "report get", lambda ns, w: with_context(ns, w, lambda ctx: get(ctx, ns.job_id, ns.report_id)))
