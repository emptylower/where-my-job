# src/where_my_job/store/evidence.py
from __future__ import annotations
import json
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from ..clock import Clock, iso_utc, parse_iso
from ..errors import InvalidInput, ErrorItem
from ..ids import new_id, canonical_json, sha256_json

EXCERPT_MAX = 16384
CLI_KINDS = ("job_detail_page", "company_page")
EXTERNAL_KINDS = ("web_page", "document", "user_statement")
PAGE_SIZE_MAX = 200
PUBLIC_COLUMNS = ("evidence_id", "job_id", "company_id", "origin", "kind", "url", "captured_at", "published_at",
                  "excerpt", "content_hash", "parser_version", "completeness", "source_note",
                  "full_text_state", "created_at")
_HASH_FIELDS = ("job_id", "company_id", "kind", "origin", "url", "captured_at", "published_at", "excerpt",
                "structured", "full_text", "parser_version", "completeness", "source_note")

PUBLIC_STRUCTURE = {
    "job_detail_page": {"jd_sections": "counts", "boss_title": "text", "boss_active_status": "text",
        "ld_json_upDate": "text", "ld_upDate_raw": "text", "ld_datePosted_raw": "text",
        "detail_salary_text": "text", "detail_exp": "text", "detail_degree": "text", "tags": "texts"},
    "company_page": {"job_count": "count", "boss_count": "count", "job_count_raw": "text",
        "boss_count_raw": "text", "industry": "text", "scale": "text", "stage": "text",
        "ld_json_upDate": "text", "ld_upDate_raw": "text"},
    "web_page": {"headline": "text", "title": "text", "publisher": "text", "summary": "text"},
    "document": {"title": "text", "publisher": "text", "summary": "text"},
    "user_statement": {"summary": "text"},
}

def _public_structure(kind, original):
    out = {}
    for key, typ in PUBLIC_STRUCTURE.get(kind, {}).items():
        if key not in original:
            continue
        value = original[key]
        if value is None:
            out[key] = None
        elif typ == "text" and isinstance(value, str):
            out[key] = value[:2000]
        elif typ == "count" and type(value) is int and value >= 0:
            out[key] = value
        elif typ == "texts" and isinstance(value, list) and all(isinstance(x, str) for x in value):
            out[key] = [x[:200] for x in value[:64]]
        elif typ == "counts" and isinstance(value, dict):
            out[key] = {k: v for k, v in value.items() if k in ("responsibilities", "requirements")
                        and type(v) is int and v >= 0}
    return out, out != original

def _public_url(value):
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            return None
        if parts.port not in (None, 443):
            return None
        return urlunsplit(("https", parts.hostname, parts.path or "/", "", ""))
    except ValueError:
        return None

def _err(code: str, message: str, path: str) -> InvalidInput:
    return InvalidInput([ErrorItem(code, message, path)])

def public_row(row) -> dict:
    """唯一公开出口：固定列 + 白名单 structured + 去参数 URL；不含 full_text 键。"""
    d = dict(row)
    out = {k: d.get(k) for k in PUBLIC_COLUMNS}
    out["url"] = _public_url(d.get("url"))
    try:
        original = json.loads(d.get("structured_json") or "{}")
    except (TypeError, ValueError):
        original = {}
    if not isinstance(original, dict):
        original = {}
    structured, truncated = _public_structure(d.get("kind"), original)
    out["structured"] = structured
    out["structured_truncated"] = bool(truncated)
    return out

def content_hash(**fields) -> str:
    """语义输入哈希：缺失的可选字段统一为 None；不含生成的 ID、run_id、created_at。"""
    return sha256_json({k: fields.get(k) for k in _HASH_FIELDS})

def check_subject(conn, *, job_id: str | None, company_id: str | None) -> None:
    if job_id is None and company_id is None:
        raise _err("SEMANTIC_INVALID", "证据必须指向岗位或公司", "$.job_id")
    if job_id is not None:
        r = conn.execute("select company_id from jobs where job_id=?", (job_id,)).fetchone()
        if r is None:
            raise _err("NOT_FOUND", f"岗位不存在: {job_id}", "$.job_id")
        if company_id is not None and r["company_id"] != company_id:
            raise _err("EVIDENCE_REF_INVALID", "company_id 不是该岗位已核实的公司", "$.company_id")
    elif conn.execute("select 1 from companies where company_id=?", (company_id,)).fetchone() is None:
        raise _err("NOT_FOUND", f"公司不存在: {company_id}", "$.company_id")

def _insert(conn, clock: Clock, *, job_id, company_id, origin, kind, url, captured_at: str, published_at,
            excerpt: str, structured: dict, full_text, parser_version, completeness, source_note,
            idempotency_key: str, run_id) -> tuple[str, bool]:
    h = content_hash(job_id=job_id, company_id=company_id, kind=kind, origin=origin, url=url,
                     captured_at=captured_at, published_at=published_at, excerpt=excerpt, structured=structured,
                     full_text=full_text, parser_version=parser_version, completeness=completeness,
                     source_note=source_note)
    existing = conn.execute("select evidence_id, content_hash from evidence where idempotency_key=?",
                            (idempotency_key,)).fetchone()
    if existing is not None:
        if existing["content_hash"] == h:
            return existing["evidence_id"], False
        raise _err("IDEMPOTENCY_CONFLICT", f"幂等键 {idempotency_key} 已存在且内容不同", "$.idempotency_key")
    check_subject(conn, job_id=job_id, company_id=company_id)
    eid = new_id("ev", clock.now())
    conn.execute("""insert into evidence(evidence_id, job_id, company_id, origin, kind, url, captured_at, published_at,
                    excerpt, structured_json, full_text, content_hash, parser_version, completeness, source_note,
                    idempotency_key, run_id, created_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (eid, job_id, company_id, origin, kind, url, captured_at, published_at, excerpt[:EXCERPT_MAX],
                  canonical_json(structured), full_text, h, parser_version, completeness, source_note,
                  idempotency_key, run_id, iso_utc(clock.now())))
    return eid, True

def insert_external(conn, clock: Clock, obj: dict, *, origin: str) -> tuple[str, bool]:
    """agent/user 提交（调用方已在同一写事务内校验）。返回 (evidence_id, created)。"""
    if origin not in ("agent", "user"):
        raise _err("SEMANTIC_INVALID", "外部证据 origin 只能是 agent 或 user", "$.origin")
    if obj.get("origin") not in (None, origin):
        raise _err("SEMANTIC_INVALID", f"文件 origin={obj.get('origin')} 与命令 origin={origin} 不一致", "$.origin")
    if obj["kind"] not in EXTERNAL_KINDS:
        raise _err("SEMANTIC_INVALID", f"外部证据不能使用 kind={obj['kind']}", "$.kind")
    return _insert(conn, clock, job_id=obj.get("job_id"), company_id=obj.get("company_id"), origin=origin,
                   kind=obj["kind"], url=obj.get("url"), captured_at=iso_utc(parse_iso(obj["captured_at"])),
                   published_at=iso_utc(parse_iso(obj["published_at"])) if obj.get("published_at") else None,
                   excerpt=obj["excerpt"], structured=obj.get("structured") or {}, full_text=obj.get("full_text"),
                   parser_version=None, completeness="complete", source_note=obj.get("source_note"),
                   idempotency_key=obj["idempotency_key"], run_id=None)

def insert_cli(conn, clock: Clock, *, job_id, company_id, kind, url, captured_at: datetime, excerpt, full_text,
               structured: dict, parser_version, completeness, run_id, idempotency_key) -> str:
    """CLI 自身采集（子计划 05 与测试种子）。返回 evidence_id。"""
    if kind not in CLI_KINDS:
        raise ValueError(f"insert_cli 只接受 {CLI_KINDS}")
    if not isinstance(excerpt, str):
        raise TypeError("excerpt 必须是字符串")
    if completeness not in ("complete", "partial", "unparsed"):
        raise ValueError("completeness 取值非法")
    eid, _ = _insert(conn, clock, job_id=job_id, company_id=company_id, origin="cli", kind=kind, url=url,
                     captured_at=iso_utc(captured_at), published_at=None, excerpt=excerpt, structured=structured,
                     full_text=full_text, parser_version=parser_version, completeness=completeness,
                     source_note="CLI 采集", idempotency_key=idempotency_key, run_id=run_id)
    return eid

def get_public(conn, evidence_id: str) -> dict | None:
    r = conn.execute("select * from v_evidence where evidence_id=?", (evidence_id,)).fetchone()
    return public_row(r) if r else None

def get_full_text(conn, evidence_id: str) -> tuple[str | None, str] | None:
    """返回 (原文, 状态)；状态为 present/absent/pruned。证据不存在返回 None。"""
    r = conn.execute("select full_text, full_text_pruned_at from evidence where evidence_id=?", (evidence_id,)).fetchone()
    if r is None:
        return None
    if r["full_text"] is not None:
        return r["full_text"], "present"
    return None, ("pruned" if r["full_text_pruned_at"] is not None else "absent")

def structured_of(conn, evidence_id: str) -> dict:
    """私有 structured，只供完整度推导，不得进入任何输出。"""
    r = conn.execute("select structured_json from evidence where evidence_id=?", (evidence_id,)).fetchone()
    if r is None:
        return {}
    value = json.loads(r[0])
    return value if isinstance(value, dict) else {}

def _job_company(conn, job_id: str) -> str | None:
    r = conn.execute("select company_id from jobs where job_id=?", (job_id,)).fetchone()
    return r["company_id"] if r else None

_JOB_SCOPE = "(e.job_id = :job OR (e.job_id IS NULL AND :company IS NOT NULL AND e.company_id = :company))"

def ids_for_job(conn, job_id: str) -> frozenset[str]:
    """本岗位专属证据 + 其已核实公司的公司级证据（job_id IS NULL）；不共享其它岗位的专属证据。"""
    rows = conn.execute(f"select e.evidence_id from evidence e where {_JOB_SCOPE}",
                        {"job": job_id, "company": _job_company(conn, job_id)}).fetchall()
    return frozenset(r[0] for r in rows)

def list_public(conn, *, job_id: str | None = None, company_id: str | None = None, page: int = 1,
                page_size: int = 50) -> tuple[list[dict], int, bool]:
    if (job_id is None) == (company_id is None):
        raise _err("SCHEMA_INVALID", "需要且只能给 job_id 或 company_id 之一", "$.job")
    if not (1 <= page_size <= PAGE_SIZE_MAX) or page < 1:
        raise _err("SEMANTIC_INVALID", f"page_size 须在 1..{PAGE_SIZE_MAX}，page >= 1", "$.page_size")
    if job_id is not None:
        where, params = _JOB_SCOPE, {"job": job_id, "company": _job_company(conn, job_id)}
    else:
        where, params = "(e.company_id = :company AND e.job_id IS NULL)", {"company": company_id}
    total = conn.execute(f"select count(*) from v_evidence e where {where}", params).fetchone()[0]
    rows = conn.execute(f"select * from v_evidence e where {where} order by e.captured_at desc, e.evidence_id desc "
                        "limit :limit offset :offset",
                        dict(params, limit=page_size, offset=(page - 1) * page_size)).fetchall()
    return [public_row(r) for r in rows], total, page * page_size < total

def latest_cli(conn, *, job_id: str | None = None, company_id: str | None = None, kind: str) -> dict | None:
    # 最新行按 (captured_at, rowid) 选取：视图没有 rowid，先在基表取 ID，再经 v_evidence 读受限列。
    if job_id is not None:
        hit = conn.execute("""select evidence_id from evidence where job_id=? and kind=? and origin='cli'
                              order by captured_at desc, rowid desc limit 1""", (job_id, kind)).fetchone()
    else:
        hit = conn.execute("""select evidence_id from evidence where company_id=? and job_id is null and kind=? and origin='cli'
                              order by captured_at desc, rowid desc limit 1""", (company_id, kind)).fetchone()
    if hit is None:
        return None
    r = conn.execute("select * from v_evidence where evidence_id=?", (hit[0],)).fetchone()
    return public_row(r) if r else None
