# src/where_my_job/store/streams.py
"""声明注册表。register 必须在调用方的 write_tx 内执行；失败抛 InvalidInput 由 write_tx 回滚。"""
from __future__ import annotations
import json, sqlite3
from ..clock import Clock, iso_utc
from ..errors import InvalidInput, ErrorItem
from ..streams import builtin as b

def get_active(conn: sqlite3.Connection, stream: str) -> dict | None:
    r = conn.execute("select stream, stream_revision, definition_json, content_hash, registered_at from stream_registry where stream=? and is_active=1",
                     (stream,)).fetchone()
    return _row(r) if r else None

def get_definition(conn, stream: str, revision: int) -> dict | None:
    r = conn.execute("select definition_json from stream_registry where stream=? and stream_revision=?", (stream, revision)).fetchone()
    return json.loads(r[0]) if r else None

def get_revision_row(conn, stream: str, revision: int) -> dict | None:
    r = conn.execute("select stream, stream_revision, definition_json, content_hash, registered_at, is_active from stream_registry where stream=? and stream_revision=?",
                     (stream, revision)).fetchone()
    return _row(r) if r else None

def list_revisions(conn, stream: str) -> list[dict]:
    return [_row(r) for r in conn.execute("select stream, stream_revision, definition_json, content_hash, registered_at, is_active from stream_registry where stream=? order by stream_revision", (stream,))]

def list_all(conn) -> list[dict]:
    return [_row(r) for r in conn.execute("select stream, stream_revision, definition_json, content_hash, registered_at, is_active from stream_registry where is_active=1 order by stream")]

def active_definitions(conn) -> dict[str, dict]:
    return {r["stream"]: r["definition"] for r in list_all(conn)}

def _row(r) -> dict:
    d = {"stream": r["stream"], "stream_revision": r["stream_revision"], "definition": json.loads(r["definition_json"]),
         "content_hash": r["content_hash"], "registered_at": r["registered_at"]}
    if "is_active" in r.keys():
        d["is_active"] = bool(r["is_active"])
    return d

def register(conn: sqlite3.Connection, clock: Clock, definition: dict) -> dict:
    """校验（静态 + 兼容）→ 插入不可变版本 → 切换 is_active。返回 {stream, stream_revision, content_hash, created}。"""
    problems = b.definition_problems(definition)
    if problems:
        raise InvalidInput([ErrorItem("UNSUPPORTED_SETTING" if p in ("$.projection", "$.latest_by") else "SEMANTIC_INVALID", m, p) for p, m in problems])
    stream, rev = definition["stream"], definition["stream_revision"]
    if stream == b.APPLICATIONS_STREAM:
        raise InvalidInput([ErrorItem("RESERVED_KEY", "applications 是内置流，不能重新注册", "$.stream")])
    h = b.definition_hash(definition)
    existing = get_revision_row(conn, stream, rev)
    if existing is not None:
        if existing["content_hash"] == h:
            return {"stream": stream, "stream_revision": rev, "content_hash": h, "created": False}
        raise InvalidInput([ErrorItem("INCOMPATIBLE_REVISION", f"版本 {rev} 已存在且内容不同；升版请用 {rev + 1}", "$.stream_revision")])
    latest = conn.execute("select max(stream_revision) from stream_registry where stream=?", (stream,)).fetchone()[0]
    if latest is None:
        if rev != 1:
            raise InvalidInput([ErrorItem("SEMANTIC_INVALID", "首个版本必须是 1", "$.stream_revision")])
    else:
        old = get_definition(conn, stream, latest)
        problems = b.compatibility_problems(old, definition)
        if problems:
            path = "$.stream_revision" if any("stream_revision" in p for p in problems) else "$.types"
            if any("subject_kind" in p for p in problems): path = "$.subject_kind"
            raise InvalidInput([ErrorItem("INCOMPATIBLE_REVISION", "; ".join(problems), path)])
    now = iso_utc(clock.now())
    conn.execute("update stream_registry set is_active=0 where stream=?", (stream,))
    conn.execute("insert into stream_registry(stream, stream_revision, definition_json, content_hash, registered_at, is_active) values (?,?,?,?,?,1)",
                 (stream, rev, json.dumps(definition, ensure_ascii=False, sort_keys=True, separators=(",", ":")), h, now))
    return {"stream": stream, "stream_revision": rev, "content_hash": h, "created": True}
