# src/where_my_job/store/events.py
"""事件追加与读取。append() 必须在调用方的 write_tx 内运行。
service.events.validate_new_request 在同一事务内先完成 schema、时间与（仅新请求的）语义校验；
本模块负责持久状态约束：版本绑定、幂等比较、主体存在、身份创建、纠错链与有效集合复核。"""
from __future__ import annotations
import json, sqlite3
from ..clock import Clock, iso_utc, parse_iso
from ..errors import InvalidInput, ErrorItem
from ..ids import new_id, canonical_json, sha256_text
from ..streams import builtin as b
from . import streams, applications

def _err(code: str, msg: str, path: str) -> InvalidInput:
    return InvalidInput([ErrorItem(code, msg, path)])

def _utc(value: str) -> str:
    return iso_utc(parse_iso(value))

def by_idempotency_key(conn, key: str):
    return conn.execute("select * from events where idempotency_key=?", (key,)).fetchone()

# ---------- 幂等：规范化语义输入 ----------

def _semantic_key_from_request(conn, req: dict, bound_revision: int) -> str:
    payload = req.get("payload") or {}
    applied = req["stream"] == b.APPLICATIONS_STREAM and req["type"] == "applied"
    # applied 的语义主体固定为输入的 (subject_kind, subject_id, payload.job_id)；
    # 已存 applied 的 subject_id 是 CLI 自动分配的，比较时还原为 None，因此显式补传 application_id 是不同输入。
    subject = [req["subject_kind"], req.get("subject_id"), payload.get("job_id") if applied else None]
    block = req.get("corrected")
    corrected = None
    if block is not None:
        replace = block.get("op") == "replace"
        corrected = {"target": block.get("corrected_event_id"), "op": block.get("op"),
                     "original_type": block.get("original_type") if replace else None,
                     "replacement_payload": block.get("replacement_payload") if replace else None,
                     "replacement_occurred_at": (_utc(block["replacement_occurred_at"])
                                                 if replace and block.get("replacement_occurred_at") else None)}
    core = {"stream": req["stream"], "stream_revision": bound_revision, "type": req["type"], "subject": subject,
            "occurred_at": _utc(req["occurred_at"]), "payload": payload, "origin": req["origin"], "corrected": corrected}
    return sha256_text(canonical_json(core))

def _semantic_key_from_row(conn, row: sqlite3.Row) -> str:
    payload = json.loads(row["payload_json"])
    if row["type"] == b.CORRECTED_TYPE:
        req = {"stream": row["stream"], "type": row["type"], "subject_kind": row["subject_kind"], "subject_id": row["subject_id"],
               "occurred_at": row["occurred_at"], "payload": {}, "origin": row["origin"],
               "corrected": {"corrected_event_id": row["corrected_event_id"], "op": payload.get("op"),
                             "original_type": payload.get("original_type"),
                             "replacement_payload": payload.get("replacement_payload"),
                             "replacement_occurred_at": payload.get("replacement_occurred_at")}}
        return _semantic_key_from_request(conn, req, row["stream_revision"])
    subject_id = row["subject_id"]
    if row["stream"] == b.APPLICATIONS_STREAM and row["type"] == "applied":
        subject_id = None
    req = {"stream": row["stream"], "type": row["type"], "subject_kind": row["subject_kind"], "subject_id": subject_id,
           "occurred_at": row["occurred_at"], "payload": payload, "origin": row["origin"]}
    return _semantic_key_from_request(conn, req, row["stream_revision"])

def same_request(conn, existing: sqlite3.Row, req: dict, bound_revision: int) -> bool:
    """已存事件与重试请求是否为同一语义输入。bound_revision 取请求自己绑定的版本，不换成已存版本。"""
    return _semantic_key_from_row(conn, existing) == _semantic_key_from_request(conn, req, bound_revision)

# ---------- 链工具 ----------

def get_event(conn, event_id: str) -> sqlite3.Row | None:
    return conn.execute("select * from events where event_id=?", (event_id,)).fetchone()

def root_of(conn, event_id: str) -> sqlite3.Row:
    row = get_event(conn, event_id)
    while row["corrected_event_id"] is not None:
        row = get_event(conn, row["corrected_event_id"])
    return row

def tail_of(conn, event_id: str) -> sqlite3.Row:
    row = get_event(conn, event_id)
    while True:
        nxt = conn.execute("select * from events where corrected_event_id=?", (row["event_id"],)).fetchone()
        if nxt is None:
            return row
        row = nxt

def _result(conn, row: sqlite3.Row, created: bool) -> dict:
    root = root_of(conn, row["event_id"]); tail = tail_of(conn, root["event_id"])
    out = {"created": created, "event_id": row["event_id"], "root_event_id": root["event_id"], "current_event_id": tail["event_id"],
           "stream": row["stream"], "stream_revision": row["stream_revision"], "type": row["type"],
           "subject_kind": row["subject_kind"], "subject_id": row["subject_id"]}
    if row["subject_kind"] == "application":
        out["application_id"] = row["subject_id"]
    return out

# ---------- 版本绑定 ----------

def _resolve_definition(conn, req: dict, existing) -> tuple[dict, int]:
    rev = req["stream_revision"]
    row = streams.get_revision_row(conn, req["stream"], rev)
    if row is None:
        if existing is not None:
            # 幂等键已被使用，而本次请求绑定了不存在的流/版本：必然与已存事件内容不同 → 冲突，而非"不存在"
            raise _err("IDEMPOTENCY_CONFLICT", f"幂等键 {req['idempotency_key']} 已用于不同内容的事件", "$.idempotency_key")
        raise _err("NOT_FOUND", "流版本不存在", "$.stream_revision")
    if existing is not None:
        return row["definition"], rev
    if req["type"] == b.CORRECTED_TYPE:
        target = get_event(conn, req["corrected"]["corrected_event_id"])
        if target is None:
            raise _err("NOT_FOUND", "纠错目标不存在", "$.corrected.corrected_event_id")
        root = root_of(conn, target["event_id"])
        if root["stream"] != req["stream"] or root["stream_revision"] != rev:
            raise _err("CORRECTION_CROSS_STREAM", "纠错必须绑定原流版本", "$.stream_revision")
    elif not row["is_active"]:
        raise _err("SEMANTIC_INVALID", "新业务事件必须使用活动版本", "$.stream_revision")
    return row["definition"], rev

resolve_definition = _resolve_definition   # service.events.validate_new_request 使用

# ---------- 追加 ----------

def append(conn: sqlite3.Connection, clock: Clock, req: dict) -> dict:
    """req 是通过 schema 校验的事件输入（必须含 stream_revision）。返回 _result()。"""
    if req["type"] == b.CORRECTED_TYPE and not isinstance(req.get("corrected"), dict):
        raise _err("SEMANTIC_INVALID", "type=corrected 必须提供 corrected 块", "$.corrected")
    existing = by_idempotency_key(conn, req["idempotency_key"])
    definition, bound_rev = _resolve_definition(conn, req, existing)
    if existing is not None:
        if same_request(conn, existing, req, bound_rev):
            return _result(conn, existing, created=False)
        raise _err("IDEMPOTENCY_CONFLICT", f"幂等键 {req['idempotency_key']} 已用于不同内容的事件", "$.idempotency_key")
    if req["type"] == b.CORRECTED_TYPE:
        return _append_correction(conn, clock, req, definition)
    if req["subject_kind"] != definition["subject_kind"]:
        raise _err("SEMANTIC_INVALID", f"流的主体类型是 {definition['subject_kind']}", "$.subject_kind")
    errs = b.check_payload(definition, req["type"], req["payload"])
    if errs:
        raise InvalidInput([ErrorItem("SEMANTIC_INVALID", m, p) for p, m in errs])
    occurred = _utc(req["occurred_at"])
    subject_id = req.get("subject_id")
    if req["stream"] == b.APPLICATIONS_STREAM and req["type"] == "applied":
        if subject_id is not None:
            raise _err("SEMANTIC_INVALID", "applied 由 CLI 创建身份，不要提供 subject_id", "$.subject_id")
        job_id = req["payload"]["job_id"]
        if conn.execute("select 1 from jobs where job_id=?", (job_id,)).fetchone() is None:
            raise _err("SUBJECT_MISSING", f"岗位不存在: {job_id}", "$.payload.job_id")
        subject_id = applications.create(conn, clock, job_id)
    else:
        _check_subject(conn, req["subject_kind"], subject_id)
        if req["stream"] == b.APPLICATIONS_STREAM:
            applied = applications.applied_at(conn, subject_id)
            if applied is not None and occurred < applied:
                raise _err("SEMANTIC_INVALID", f"{req['type']} 的发生时间早于投递时间 {applied}", "$.occurred_at")
    event_id = new_id("evt", clock.now())
    conn.execute("""insert into events(event_id, stream, stream_revision, type, subject_kind, subject_id, occurred_at, recorded_at,
                    payload_json, idempotency_key, corrected_event_id, origin) values (?,?,?,?,?,?,?,?,?,?,NULL,?)""",
                 (event_id, req["stream"], bound_rev, req["type"], req["subject_kind"], subject_id, occurred,
                  iso_utc(clock.now()), canonical_json(req["payload"]), req["idempotency_key"], req["origin"]))
    return _result(conn, get_event(conn, event_id), created=True)

def _check_subject(conn, kind: str, subject_id: str | None) -> None:
    if kind == "none":
        if subject_id is not None:
            raise _err("SEMANTIC_INVALID", "subject_kind=none 时 subject_id 必须为空", "$.subject_id")
        return
    if not subject_id:
        raise _err("SEMANTIC_INVALID", "必须提供主体 ID", "$.subject_id")
    if kind == "job":
        ok = conn.execute("select 1 from jobs where job_id=?", (subject_id,)).fetchone() is not None
    elif kind == "company":
        ok = conn.execute("select 1 from companies where company_id=?", (subject_id,)).fetchone() is not None
    else:
        ok = applications.get(conn, subject_id) is not None and applications.has_effective_applied(conn, subject_id)
    if not ok:
        raise _err("SUBJECT_MISSING", f"主体不存在或无效: {kind} {subject_id}", "$.subject_id")

# --- store/events.py 追加（替换 Task 5 的 _append_correction） ---
import sqlite3 as _sqlite3

def fork_error(e: Exception) -> InvalidInput:
    return InvalidInput([ErrorItem("CORRECTION_FORK", f"纠错目标已被其他纠错占用（并发分叉）: {e}", "$.corrected.corrected_event_id")])

def _effective_rows_for_application(conn, application_id: str) -> list[sqlite3.Row]:
    return conn.execute("""select * from v_effective_events where subject_kind='application' and subject_id=?
                           order by occurred_at, current_recorded_at, root_id""", (application_id,)).fetchall()

def _check_effective_application(conn, application_id: str) -> None:
    rows = conn.execute("""select stream, type, occurred_at
        from v_effective_events
        where subject_kind='application' and subject_id=?""", (application_id,)).fetchall()
    applied = [r for r in rows if r["stream"] == b.APPLICATIONS_STREAM and r["type"] == "applied"]
    dependent = [r for r in rows if not (r["stream"] == b.APPLICATIONS_STREAM and r["type"] == "applied")]
    if len(applied) > 1:
        raise _err("SEMANTIC_INVALID", "同一投递身份只能有一个有效 applied", "$.corrected")
    if dependent and not applied:
        raise _err("DEPENDENT_EVENTS", "有效后续事件必须依赖有效 applied", "$.corrected")
    if applied:
        start = parse_iso(applied[0]["occurred_at"])
        if any(r["stream"] == b.APPLICATIONS_STREAM and parse_iso(r["occurred_at"]) < start for r in dependent):
            raise _err("SEMANTIC_INVALID", "后续事件不能早于有效投递时间", "$.corrected")

def _append_correction(conn, clock: Clock, req: dict, definition: dict) -> dict:
    """调用前 append() 已经：按请求版本解析定义、确认目标存在且根事件同流同版本、完成幂等查找。"""
    block = req["corrected"]
    errs = b.check_corrected_block(block)
    if errs:
        raise InvalidInput([ErrorItem("SEMANTIC_INVALID", m, p) for p, m in errs])
    target = get_event(conn, block["corrected_event_id"])
    if target is None:
        raise _err("NOT_FOUND", f"目标事件不存在: {block['corrected_event_id']}", "$.corrected.corrected_event_id")
    if target["stream"] != req["stream"]:
        raise _err("CORRECTION_CROSS_STREAM", "纠错必须与目标同流", "$.stream")
    if target["subject_kind"] != req["subject_kind"] or target["subject_id"] != req.get("subject_id"):
        raise _err("CORRECTION_CROSS_STREAM", "纠错必须与目标同主体", "$.subject_id")
    if conn.execute("select 1 from events where corrected_event_id=?", (target["event_id"],)).fetchone() is not None:
        tail = tail_of(conn, target["event_id"])
        raise _err("CORRECTION_NOT_TAIL", f"目标不是链末端；当前末端是 {tail['event_id']}", "$.corrected.corrected_event_id")
    root = root_of(conn, target["event_id"])
    root_definition = streams.get_definition(conn, root["stream"], root["stream_revision"])   # 按原业务事件的定义校验
    op = block["op"]
    stored_payload: dict = {"op": op}
    if op == "replace":
        if block["original_type"] != root["type"]:
            raise _err("SEMANTIC_INVALID", f"replace 不能更换业务类型（原类型 {root['type']}）", "$.corrected.original_type")
        errs = b.check_payload(root_definition, root["type"], block["replacement_payload"])
        if errs:
            raise InvalidInput([ErrorItem("SEMANTIC_INVALID", m, p.replace("$.payload", "$.corrected.replacement_payload")) for p, m in errs])
        if root["stream"] == b.APPLICATIONS_STREAM and root["type"] == "applied":
            app = applications.get(conn, root["subject_id"])
            if block["replacement_payload"].get("job_id") != app["job_id"]:
                raise _err("SEMANTIC_INVALID", "投递身份与岗位的关系不可通过纠错更换", "$.corrected.replacement_payload.job_id")
        stored_payload.update({"original_type": root["type"], "replacement_payload": block["replacement_payload"],
                               "replacement_occurred_at": _utc(block["replacement_occurred_at"])})
    else:  # retract
        if root["stream"] == b.APPLICATIONS_STREAM and root["type"] == "applied":
            deps = [r for r in _effective_rows_for_application(conn, root["subject_id"]) if r["root_id"] != root["event_id"]]
            if deps:
                raise InvalidInput([ErrorItem("DEPENDENT_EVENTS",
                    f"该投递仍有 {len(deps)} 条有效依赖事件（{', '.join(sorted({d['stream'] + '/' + d['type'] for d in deps}))}），先撤销它们",
                    "$.corrected.corrected_event_id")])
    event_id = new_id("evt", clock.now())
    try:
        # 纠错控制事件保存自己的 occurred_at；被替代事实的时间只在 payload.replacement_occurred_at，供有效事件投影使用
        conn.execute("""insert into events(event_id, stream, stream_revision, type, subject_kind, subject_id, occurred_at, recorded_at,
                        payload_json, idempotency_key, corrected_event_id, origin) values (?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (event_id, root["stream"], root["stream_revision"], b.CORRECTED_TYPE, target["subject_kind"], target["subject_id"],
                      _utc(req["occurred_at"]), iso_utc(clock.now()), canonical_json(stored_payload), req["idempotency_key"],
                      target["event_id"], req["origin"]))
    except _sqlite3.IntegrityError as e:
        raise fork_error(e)
    # 事务内复核：只有一个后继
    if conn.execute("select count(*) from events where corrected_event_id=?", (target["event_id"],)).fetchone()[0] != 1:
        raise fork_error(Exception("multiple successors"))
    # 业务时间一致性（applications 流）：给出精确字段路径
    if root["subject_kind"] == "application":
        app_id = root["subject_id"]
        applied = applications.applied_at(conn, app_id)
        if applied is not None:
            for r in _effective_rows_for_application(conn, app_id):
                if r["stream"] == b.APPLICATIONS_STREAM and r["type"] != "applied" and r["occurred_at"] < applied:
                    raise _err("SEMANTIC_INVALID", f"纠错后 {r['type']}({r['occurred_at']}) 早于投递时间 {applied}",
                               "$.corrected.replacement_occurred_at" if op == "replace" else "$.corrected.corrected_event_id")
        # 纠错后有效集合复核：唯一 applied、依赖存在、内置后续事件不早于投递（恢复路径同样约束）
        _check_effective_application(conn, app_id)
    return _result(conn, get_event(conn, event_id), created=True)

# --- store/events.py 追加：读取 ---
TIMELINE_MAX_LIMIT = 1000
HISTORY_MAX_LIMIT = 2000

def _check_page(limit, offset, maximum: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise _err("SEMANTIC_INVALID", f"limit 须为 1..{maximum} 的整数", "$.limit")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise _err("SEMANTIC_INVALID", "offset 须为非负整数", "$.offset")

def _page(items: list[dict], total: int, limit: int, offset: int) -> dict:
    return {"items": items, "total": total, "limit": limit, "offset": offset, "truncated": offset + len(items) < total}

def _require_stream(conn, stream: str) -> None:
    if not streams.list_revisions(conn, stream):
        raise _err("NOT_FOUND", f"流不存在: {stream}", "$.stream")

def _fields_view(definition: dict, type_name: str, payload: dict) -> dict:
    fields = definition["types"].get(type_name, {}).get("fields", {})
    return {name: ({"present": True, "value": payload[name]} if name in payload else {"present": False, "value": None})
            for name in fields}

def timeline_page(conn, stream: str, *, subject_id: str | None = None,
                  limit: int = TIMELINE_MAX_LIMIT, offset: int = 0) -> dict:
    """有效事件（纠错已解析），按 (occurred_at, current_recorded_at, root_id) 稳定排序；返回 items/total/limit/offset/truncated。"""
    _check_page(limit, offset, TIMELINE_MAX_LIMIT)
    _require_stream(conn, stream)
    where, params = "stream=?", [stream]
    if subject_id is not None:
        where += " and subject_id=?"; params.append(subject_id)
    total = conn.execute(f"select count(*) from v_effective_events where {where}", params).fetchone()[0]
    rows = conn.execute(f"""select * from v_effective_events where {where}
                            order by occurred_at, current_recorded_at, root_id limit ? offset ?""",
                        params + [limit, offset]).fetchall()
    defs: dict[int, dict] = {}
    items = []
    for r in rows:
        rev = r["stream_revision"]
        if rev not in defs:
            defs[rev] = streams.get_definition(conn, stream, rev) or {"types": {}}
        payload = json.loads(r["payload_json"]) if r["payload_json"] else {}
        items.append({"root_event_id": r["root_id"], "current_event_id": r["current_id"], "stream": stream, "stream_revision": rev,
                      "type": r["type"], "subject_kind": r["subject_kind"], "subject_id": r["subject_id"], "origin": r["origin"],
                      "occurred_at": r["occurred_at"], "recorded_at": r["current_recorded_at"], "corrected": bool(r["corrected"]),
                      "fields": _fields_view(defs[rev], r["type"], payload)})
    return _page(items, total, limit, offset)

def _history_item(r) -> dict:
    payload = json.loads(r["payload_json"])
    item = {"event_id": r["event_id"], "stream": r["stream"], "stream_revision": r["stream_revision"], "type": r["type"],
            "subject_kind": r["subject_kind"], "subject_id": r["subject_id"], "occurred_at": r["occurred_at"],
            "recorded_at": r["recorded_at"], "origin": r["origin"], "corrected_event_id": r["corrected_event_id"],
            "superseded_by": r["superseded_by"]}
    if r["type"] == b.CORRECTED_TYPE:
        item.update({"op": payload.get("op"), "original_type": payload.get("original_type"),
                     "replacement_payload": payload.get("replacement_payload"),
                     "replacement_occurred_at": payload.get("replacement_occurred_at")})
    else:
        item["payload"] = payload
    return item

def stream_history_page(conn, stream: str, *, subject_id: str | None = None,
                        limit: int = HISTORY_MAX_LIMIT, offset: int = 0) -> dict:
    """流内全部原始行（含 corrected 与被撤销记录），按 (recorded_at, event_id)。"""
    _check_page(limit, offset, HISTORY_MAX_LIMIT)
    _require_stream(conn, stream)
    where, params = "stream=?", [stream]
    if subject_id is not None:
        where += " and subject_id=?"; params.append(subject_id)
    total = conn.execute(f"select count(*) from v_events where {where}", params).fetchone()[0]
    rows = conn.execute(f"select * from v_events where {where} order by recorded_at, event_id limit ? offset ?",
                        params + [limit, offset]).fetchall()
    return _page([_history_item(r) for r in rows], total, limit, offset)

_CHAIN_CTE = """with recursive ch(id, depth) as (
  select ?, 0
  union all
  select e.event_id, ch.depth + 1 from ch join events e on e.corrected_event_id = ch.id
)"""

def history_page(conn, event_id: str, *, limit: int = HISTORY_MAX_LIMIT, offset: int = 0) -> dict:
    """一条根事件的完整纠错链（根在前，按链深度）。传入链上任意事件都从其根开始。"""
    _check_page(limit, offset, HISTORY_MAX_LIMIT)
    if get_event(conn, event_id) is None:
        raise _err("NOT_FOUND", f"事件不存在: {event_id}", "$.event_id")
    root_id = root_of(conn, event_id)["event_id"]
    total = conn.execute(_CHAIN_CTE + " select count(*) from ch", (root_id,)).fetchone()[0]
    rows = conn.execute(_CHAIN_CTE + """ select v.*, ch.depth as chain_depth from ch join v_events v on v.event_id = ch.id
                                         order by ch.depth limit ? offset ?""", (root_id, limit, offset)).fetchall()
    items = [dict(_history_item(r), chain_depth=r["chain_depth"]) for r in rows]
    return {"root_event_id": root_id, **_page(items, total, limit, offset)}
