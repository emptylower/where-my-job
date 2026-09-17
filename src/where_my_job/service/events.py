# src/where_my_job/service/events.py
from __future__ import annotations
from ..config.loader import read_json_file
from ..errors import InvalidInput, ErrorItem
from ..store import db, events as store
from ..streams import builtin as b
from ..validate import Facts, Issue
from ..validate.schema import schema_issues
from ..validate.semantic import event as event_semantic
from .bootstrap import with_context
from .context import Context
from .facts import build_facts

def _raise(issues: list[Issue]) -> None:
    raise InvalidInput([ErrorItem(i.code, i.message, i.path) for i in issues])

def facts_for_events(ctx: Context, obj: dict) -> Facts:
    """validate event|stream 的事实快照。子计划 04 的 validate_cmd 从这里导入，签名不得改。"""
    return build_facts(ctx.conn)

def validate_new_request(ctx: Context, req) -> dict:
    """事件请求的完整校验。调用方持有事务：event add 用 write_tx（随后 append），validate event 用 read_tx。
    顺序：schema → 时间解析 → corrected 块结构 → 幂等键查找 → 按请求版本解析定义 →
    已存请求只比较完整语义键（相同即通过，不要求流仍活动或主体仍有效）；新请求才做语义校验。"""
    if not isinstance(req, dict):
        _raise([Issue("SCHEMA_INVALID", "$", "事件文件顶层必须是对象")])
    issues = schema_issues("event", req)
    if issues:
        _raise(issues)
    issues = event_semantic.time_issues(req)
    if issues:
        _raise(issues)
    if req["type"] == b.CORRECTED_TYPE:
        block = req.get("corrected")
        if block is None:
            _raise([Issue("SEMANTIC_INVALID", "$.corrected", "type=corrected 必须提供 corrected 块")])
        block_issues = [event_semantic.issue_from(p, m) for p, m in b.check_corrected_block(block)]
        if block_issues:
            _raise(block_issues)
    existing = store.by_idempotency_key(ctx.conn, req["idempotency_key"])
    definition, bound_rev = store.resolve_definition(ctx.conn, req, existing)
    if existing is not None:
        if store.same_request(ctx.conn, existing, req, bound_rev):
            return {"existing": True, "event_id": existing["event_id"], "stream_revision": bound_rev}
        _raise([Issue("IDEMPOTENCY_CONFLICT", "$.idempotency_key", f"幂等键 {req['idempotency_key']} 已用于不同内容的事件")])
    issues = event_semantic.check(req, build_facts(ctx.conn), definition=definition)
    if issues:
        _raise(issues)
    return {"existing": False, "event_id": None, "stream_revision": bound_rev}

def add_cmd(ctx: Context, file: str) -> dict:
    req = read_json_file(file)                  # 只读一次；校验与写入使用同一对象
    with db.write_tx(ctx.conn):
        validate_new_request(ctx, req)
        return store.append(ctx.conn, ctx.clock, req)

def _meta(page: dict) -> dict:
    return {k: page[k] for k in ("total", "limit", "offset", "truncated")}

def list_cmd(ctx: Context, stream: str, subject: str | None, history: bool, limit: int, offset: int,
             history_limit: int, history_offset: int) -> dict:
    with db.read_tx(ctx.conn):
        page = store.timeline_page(ctx.conn, stream, subject_id=subject, limit=limit, offset=offset)
        data = {"stream": stream, "subject_id": subject, "events": page["items"], "page": _meta(page),
                "as_of": ctx.conn.execute("select wmj_as_of()").fetchone()[0]}
        if history:
            hp = store.stream_history_page(ctx.conn, stream, subject_id=subject, limit=history_limit, offset=history_offset)
            data["history"] = hp["items"]
            data["history_page"] = _meta(hp)
    return data

def register(sub, set_handler):
    p = sub.add_parser("event", help="事件追加与时间线")
    s = p.add_subparsers(dest="event_cmd"); s.required = True
    a = s.add_parser("add"); a.add_argument("--file", required=True)
    set_handler(a, "event add", lambda ns, w: with_context(ns, w, lambda ctx: add_cmd(ctx, ns.file), write=True))
    l = s.add_parser("list")
    l.add_argument("--stream", required=True); l.add_argument("--subject"); l.add_argument("--history", action="store_true")
    l.add_argument("--limit", type=int, default=store.TIMELINE_MAX_LIMIT)
    l.add_argument("--offset", type=int, default=0)
    l.add_argument("--history-limit", type=int, default=store.HISTORY_MAX_LIMIT)
    l.add_argument("--history-offset", type=int, default=0)
    set_handler(l, "event list", lambda ns, w: with_context(ns, w, lambda ctx: list_cmd(
        ctx, ns.stream, ns.subject, ns.history, ns.limit, ns.offset, ns.history_limit, ns.history_offset)))
