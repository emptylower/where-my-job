# src/where_my_job/service/streams.py
from __future__ import annotations
from ..config.loader import read_json_file, validate_object
from ..errors import InvalidInput, ErrorItem
from ..store import db, streams as store
from .bootstrap import with_context
from .context import Context

def register_cmd(ctx: Context, file: str) -> dict:
    obj = read_json_file(file)                               # 只读一次文件
    definition = validate_object("stream", obj)              # 对同一对象做 schema + 语义校验
    with db.write_tx(ctx.conn):
        return store.register(ctx.conn, ctx.clock, definition)

def list_cmd(ctx: Context) -> dict:
    return {"streams": [{"stream": s["stream"], "stream_revision": s["stream_revision"], "content_hash": s["content_hash"],
                         "registered_at": s["registered_at"], "subject_kind": s["definition"]["subject_kind"],
                         "types": sorted(s["definition"]["types"])} for s in store.list_all(ctx.conn)]}

def show_cmd(ctx: Context, stream: str, revision: int | None) -> dict:
    revs = store.list_revisions(ctx.conn, stream)
    if not revs:
        raise InvalidInput([ErrorItem("NOT_FOUND", f"流不存在: {stream}", "$.stream")])
    row = store.get_revision_row(ctx.conn, stream, revision) if revision is not None else store.get_active(ctx.conn, stream)
    if row is None:
        raise InvalidInput([ErrorItem("NOT_FOUND", f"流 {stream} 没有版本 {revision}", "$.revision")])
    active = store.get_active(ctx.conn, stream)
    return {"stream": stream, "stream_revision": row["stream_revision"], "content_hash": row["content_hash"],
            "registered_at": row["registered_at"], "is_active": (active is not None and active["stream_revision"] == row["stream_revision"]),
            "definition": row["definition"],
            "revisions": [{"stream_revision": r["stream_revision"], "content_hash": r["content_hash"], "registered_at": r["registered_at"], "is_active": r["is_active"]} for r in revs]}

def register(sub, set_handler):
    p = sub.add_parser("stream", help="事件流声明：注册（激活不可变版本）、列表、查看")
    s = p.add_subparsers(dest="stream_cmd"); s.required = True
    r = s.add_parser("register"); r.add_argument("--file", required=True)
    set_handler(r, "stream register", lambda ns, w: with_context(ns, w, lambda ctx: register_cmd(ctx, ns.file), write=True))
    l = s.add_parser("list")
    set_handler(l, "stream list", lambda ns, w: with_context(ns, w, list_cmd))
    g = s.add_parser("show"); g.add_argument("stream"); g.add_argument("--revision", type=int)
    set_handler(g, "stream show", lambda ns, w: with_context(ns, w, lambda ctx: show_cmd(ctx, ns.stream, ns.revision)))
