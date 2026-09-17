# src/where_my_job/store/attrs.py
"""标注层契约（设计 v3 §4.2）。"""
from __future__ import annotations
import json, math, re
from ..clock import Clock, iso_utc
from ..errors import InvalidInput, ErrorItem
from .db import Connection

RESERVED = {"authentic", "jd_translation", "score", "rule_score", "tier", "dir", "excluded", "match_state", "report_state"}
PRIORITY = ("focus", "normal", "later")
NOTE_MAX = 2000
CUSTOM_MAX_BYTES = 8 * 1024
CUSTOM_MAX_KEYS = 64
_CUSTOM = re.compile(r"^custom\.[a-z][a-z0-9_]{0,62}$")

def _bad(path, msg, code="SEMANTIC_INVALID"):
    return InvalidInput([ErrorItem(code, msg, path)])

def validate_attr(key: str, value, source: str) -> str:
    """返回 value_json；不合法抛 InvalidInput。"""
    if source not in ("agent", "user"):
        raise _bad("$.source", "source 只能是 agent 或 user")
    if key in RESERVED:
        raise _bad("$.key", f"{key} 是保留名，只能经 report set / match 写入", "RESERVED_KEY")
    if key == "priority":
        if value not in PRIORITY: raise _bad("$.value", f"priority 只能是 {PRIORITY}")
    elif key == "note":
        if not isinstance(value, str) or not value.strip() or len(value) > NOTE_MAX:
            raise _bad("$.value", f"note 须为 1..{NOTE_MAX} 字符纯文本")
    elif key == "score_adjustment":
        if source != "user": raise _bad("$.source", "v1 只接受用户明确要求的分数调整")
        if not isinstance(value, dict) or set(value) != {"delta", "reason", "match_run_id"}:
            raise _bad("$.value", "score_adjustment 需要 {delta, reason, match_run_id}")
        d = value["delta"]
        if isinstance(d, bool) or not isinstance(d, (int, float)) or not math.isfinite(d) or not -100 <= d <= 100:
            raise _bad("$.value.delta", "delta 须为 -100..100 的有限数值")
        if not isinstance(value["reason"], str) or not value["reason"].strip():
            raise _bad("$.value.reason", "reason 非空")
        if not isinstance(value["match_run_id"], str) or not value["match_run_id"]:
            raise _bad("$.value.match_run_id", "需要关联的 match_run_id")
    elif _CUSTOM.match(key):
        pass
    else:
        raise _bad("$.key", "key 只能是 priority/note/score_adjustment 或 custom.<小写标识符>")
    try:
        vj = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (ValueError, TypeError) as e:
        raise _bad("$.value", f"值必须是有限的 JSON 数据: {e}")
    if len(vj.encode("utf-8")) > CUSTOM_MAX_BYTES:
        raise _bad("$.value", f"单值超过 {CUSTOM_MAX_BYTES} 字节")
    return vj

def set_attr(conn: Connection, clock: Clock, job_id: str, key: str, value, *, source: str,
             based_on_revision: str | None = None) -> None:
    vj = validate_attr(key, value, source)
    if conn.execute("select 1 from jobs where job_id=?", (job_id,)).fetchone() is None:
        raise _bad("$.job_id", f"岗位不存在: {job_id}", "NOT_FOUND")
    if key.startswith("custom."):
        n = conn.execute("select count(*) from job_attrs where job_id=? and source=? and key like 'custom.%' and key<>?",
                         (job_id, source, key)).fetchone()[0]
        if n >= CUSTOM_MAX_KEYS:
            raise _bad("$.key", f"每岗位每来源最多 {CUSTOM_MAX_KEYS} 个自定义键")
    conn.execute("""insert into job_attrs(job_id, key, value_json, source, based_on_revision, updated_at) values (?,?,?,?,?,?)
                    on conflict(job_id, key, source) do update set value_json=excluded.value_json,
                    based_on_revision=excluded.based_on_revision, updated_at=excluded.updated_at""",
                 (job_id, key, vj, source, based_on_revision, iso_utc(clock.now())))

def unset_attr(conn, job_id: str, key: str, *, source: str) -> int:
    return conn.execute("delete from job_attrs where job_id=? and key=? and source=?", (job_id, key, source)).rowcount

def get_attr(conn, job_id: str, key: str) -> list[dict]:
    rows = conn.execute("select key, value_json, source, based_on_revision, updated_at from job_attrs where job_id=? and key=? order by source desc",
                        (job_id, key)).fetchall()   # user 在前
    return [dict(r, value=json.loads(r["value_json"])) for r in rows]

def list_attrs(conn, job_id: str) -> list[dict]:
    rows = conn.execute("select key, value_json, source, based_on_revision, updated_at from job_attrs where job_id=? order by key, source desc", (job_id,)).fetchall()
    return [dict(r, value=json.loads(r["value_json"])) for r in rows]
