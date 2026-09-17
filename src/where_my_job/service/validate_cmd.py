# src/where_my_job/service/validate_cmd.py
from __future__ import annotations
from ..config import loader                          # 经模块调用：子计划 01 的测试会 monkeypatch loader.read_json_file
from ..errors import InvalidInput, ErrorItem
from ..store import db
from ..validate import KINDS
from ..validate.schema import schema_issues

DB_KINDS = ("evidence", "report", "event", "stream")

def _schema_first(kind: str, obj: dict) -> None:
    """查库前先做纯 schema 校验：字段类型错误（例如 job_id 为数组）返回 SCHEMA_INVALID / 退出 1。"""
    issues = schema_issues(kind, obj)
    if issues:
        raise InvalidInput([ErrorItem(i.code, i.message, i.path) for i in issues])

def run(ns, warnings) -> dict:
    obj = loader.read_json_file(ns.file)              # 只读一次；后续事实选择与校验都用这份对象
    if ns.kind not in DB_KINDS:
        loader.validate_object(ns.kind, obj, None)
        return {"kind": ns.kind, "issues": []}
    _schema_first(ns.kind, obj)
    from .bootstrap import with_context

    def _go(ctx):
        with db.read_tx(ctx.conn):
            if ns.kind == "event":
                from .events import validate_new_request
                validate_new_request(ctx, obj)
            elif ns.kind == "stream":
                from .events import facts_for_events
                loader.validate_object("stream", obj, facts_for_events(ctx, obj))
            else:
                from .evidence import facts_for
                loader.validate_object(ns.kind, obj, facts_for(ctx, obj.get("job_id")))
        return {"kind": ns.kind, "issues": []}

    return with_context(ns, warnings, _go)

def register(sub, set_handler):
    p = sub.add_parser("validate", help="只校验，不激活、不采集")
    p.add_argument("kind", choices=list(KINDS))
    p.add_argument("file")
    set_handler(p, "validate", run)
