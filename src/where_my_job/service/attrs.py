# src/where_my_job/service/attrs.py
from __future__ import annotations
import json
from ..store import db, attrs
from .bootstrap import with_context
from .context import Context

def _parse_value(text: str):
    """尝试按 JSON 解析（true/false/数字/对象/数组/带引号字符串）；失败按纯字符串。NaN/Infinity 由存储层拒绝。"""
    try:
        return json.loads(text)
    except ValueError:
        return text

def set_(ctx: Context, ns) -> dict:
    value = _parse_value(ns.value)
    with db.write_tx(ctx.conn):
        attrs.set_attr(ctx.conn, ctx.clock, ns.job_id, ns.key, value, source=ns.source, based_on_revision=ns.based_on)
    return {"job_id": ns.job_id, "key": ns.key, "source": ns.source}

def get(ctx: Context, ns) -> dict:
    vals = attrs.get_attr(ctx.conn, ns.job_id, ns.key)
    return {"job_id": ns.job_id, "key": ns.key,
            "values": [{"source": v["source"], "value": v["value"], "based_on_revision": v["based_on_revision"], "updated_at": v["updated_at"]} for v in vals]}

def list_(ctx: Context, ns) -> dict:
    return {"job_id": ns.job_id, "attrs": [{k: v for k, v in a.items() if k != "value_json"} for a in attrs.list_attrs(ctx.conn, ns.job_id)]}

def unset(ctx: Context, ns) -> dict:
    with db.write_tx(ctx.conn):
        n = attrs.unset_attr(ctx.conn, ns.job_id, ns.key, source=ns.source)
    return {"job_id": ns.job_id, "key": ns.key, "source": ns.source, "removed": n}

def register(sub, set_handler):
    p = sub.add_parser("attr", help="标注读写")
    s = p.add_subparsers(dest="attr_cmd"); s.required = True
    a = s.add_parser("set"); a.add_argument("job_id"); a.add_argument("key"); a.add_argument("value")
    a.add_argument("--source", choices=["agent", "user"], required=True); a.add_argument("--based-on")
    set_handler(a, "attr set", lambda ns, w: with_context(ns, w, lambda ctx: set_(ctx, ns), write=True))
    g = s.add_parser("get"); g.add_argument("job_id"); g.add_argument("key")
    set_handler(g, "attr get", lambda ns, w: with_context(ns, w, lambda ctx: get(ctx, ns)))
    l = s.add_parser("list"); l.add_argument("job_id")
    set_handler(l, "attr list", lambda ns, w: with_context(ns, w, lambda ctx: list_(ctx, ns)))
    u = s.add_parser("unset"); u.add_argument("job_id"); u.add_argument("key"); u.add_argument("--source", choices=["agent", "user"], required=True)
    set_handler(u, "attr unset", lambda ns, w: with_context(ns, w, lambda ctx: unset(ctx, ns), write=True))
