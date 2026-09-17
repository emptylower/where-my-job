# src/where_my_job/store/reports.py
from __future__ import annotations
import json
from ..clock import Clock, iso_utc
from ..errors import InvalidInput, ErrorItem
from ..ids import new_id, canonical_json, sha256_json
from . import bundles as bundle_repo
from . import evidence as ev_repo

REPORT_VERSION = 1
PROJECTED_KEYS = ("authentic", "jd_translation")
_HASH_KEYS = ("schema_version", "job_id", "bundle_id", "extra_evidence_ids", "profile_revision", "authentic",
              "jd_translation", "mismatches", "resume_advice", "report_md")

def _err(code: str, message: str, path: str) -> InvalidInput:
    return InvalidInput([ErrorItem(code, message, path)])

def request_hash(obj: dict) -> str:
    """请求语义哈希：缺失的 extra_evidence_ids 规范为 []；不含服务端生成字段。"""
    norm = {k: obj.get(k) for k in _HASH_KEYS}
    norm["extra_evidence_ids"] = list(obj.get("extra_evidence_ids") or [])
    return sha256_json(norm)

def find_by_key(conn, key: str):
    return conn.execute("select report_id, structured_json from deepdives where idempotency_key=?", (key,)).fetchone()

def _refs(obj: dict) -> list[tuple[str, str]]:
    out = []
    for arr in ("facts", "supporting", "opposing"):
        for i, item in enumerate(obj["authentic"][arr]):
            out.append((item["evidence_id"], f"$.authentic.{arr}[{i}].evidence_id"))
    for i, s in enumerate(obj["jd_translation"]["sentences"]):
        if "evidence_id" in s:
            out.append((s["evidence_id"], f"$.jd_translation.sentences[{i}].evidence_id"))
    for i, m in enumerate(obj["mismatches"]):
        if "evidence_id" in m:
            out.append((m["evidence_id"], f"$.mismatches[{i}].evidence_id"))
    return out

def check_submission(conn, obj: dict) -> list[str]:
    """写事务内调用，顺序固定：当前包 → 补充证据归属 → 引用闭包。返回去重后的补充证据 ID。"""
    job_id = obj["job_id"]
    current = bundle_repo.current_for_job(conn, job_id)
    if current is None or current["job_id"] != job_id or current["bundle_id"] != obj["bundle_id"]:
        raise _err("BUNDLE_STALE",
                   f"bundle {obj['bundle_id']} 不是该岗位当前证据包（当前 {current['bundle_id'] if current else '无'}）；"
                   "请基于当前包重写报告", "$.bundle_id")
    available = ev_repo.ids_for_job(conn, job_id)
    extras: list[str] = []
    for i, eid in enumerate(obj.get("extra_evidence_ids") or []):
        if eid not in available:
            raise _err("EVIDENCE_REF_INVALID", f"补充证据不属于该岗位: {eid}", f"$.extra_evidence_ids[{i}]")
        if eid not in extras:
            extras.append(eid)
    closure = set(current["evidence_ids"]) | set(extras)
    for eid, path in _refs(obj):
        if eid not in available or eid not in closure:
            raise _err("EVIDENCE_REF_INVALID", f"引用 {eid} 不在绑定证据包与声明的补充证据中", path)
    return extras

def _structured(obj: dict, report_id: str, extras: list[str]) -> dict:
    return {"authentic": dict(obj["authentic"], report_id=report_id),
            "jd_translation": obj["jd_translation"],
            "mismatches": obj["mismatches"],
            "resume_advice": obj["resume_advice"],
            "extra_evidence_ids": extras}

def insert(conn, clock: Clock, obj: dict) -> tuple[str, bool]:
    """调用方持有写事务，且新请求已通过 validate。已存幂等键先比较，再做当前包与闭包校验，最后派生、插入、投影。"""
    key = obj["idempotency_key"]
    h = request_hash(obj)
    existing = find_by_key(conn, key)
    if existing is not None:
        if json.loads(existing["structured_json"]).get("_content_hash") == h:
            return existing["report_id"], False
        raise _err("IDEMPOTENCY_CONFLICT", f"幂等键 {key} 已存在且内容不同", "$.idempotency_key")
    extras = check_submission(conn, obj)
    bundle_id = obj["bundle_id"]
    base = bundle_repo.get(conn, bundle_id)
    if any(e not in base["evidence_ids"] for e in extras):
        bundle_id = bundle_repo.derive(conn, clock, base_bundle_id=bundle_id, extra_evidence_ids=extras)
    rid = new_id("rpt", clock.now())
    structured = _structured(obj, rid, extras)
    structured["_content_hash"] = h
    structured["bound_bundle_id"] = bundle_id
    now = iso_utc(clock.now())
    conn.execute("""insert into deepdives(report_id, job_id, bundle_id, report_md, structured_json, profile_revision,
                    report_version, idempotency_key, created_at) values (?,?,?,?,?,?,?,?,?)""",
                 (rid, obj["job_id"], bundle_id, obj["report_md"], canonical_json(structured), obj["profile_revision"],
                  REPORT_VERSION, key, now))
    for k in PROJECTED_KEYS:
        conn.execute("""insert into job_attrs(job_id, key, value_json, source, based_on_revision, updated_at)
                        values (?,?,?,'agent',?,?)
                        on conflict(job_id, key, source) do update set value_json=excluded.value_json,
                          based_on_revision=excluded.based_on_revision, updated_at=excluded.updated_at""",
                     (obj["job_id"], k, canonical_json(structured[k]), rid, now))
    return rid, True

def _state_for(conn, job_id: str, report_id: str) -> tuple[str, bool, str | None]:
    row = conn.execute("select current_bundle_id, report_id, report_state from v_jobs where job_id=?", (job_id,)).fetchone()
    is_current = row is not None and row["report_id"] == report_id
    return (row["report_state"] if is_current else "stale"), is_current, (row["current_bundle_id"] if row else None)

def persisted_summary(conn, report_id: str) -> dict:
    r = conn.execute("""select d.report_id, d.job_id, d.bundle_id, b.bundle_version from deepdives d
                        join evidence_bundles b on b.bundle_id = d.bundle_id where d.report_id=?""", (report_id,)).fetchone()
    state, _, _ = _state_for(conn, r["job_id"], report_id)
    return {"report_id": r["report_id"], "bundle_id": r["bundle_id"], "bundle_version": r["bundle_version"],
            "report_state": state}

def get(conn, job_id: str, *, report_id: str | None) -> dict | None:
    if report_id:
        r = conn.execute("select * from deepdives where job_id=? and report_id=?", (job_id, report_id)).fetchone()
    else:
        r = conn.execute("select * from deepdives where job_id=? order by created_at desc, rowid desc limit 1",
                         (job_id,)).fetchone()
    if r is None:
        return None
    structured = json.loads(r["structured_json"])
    structured.pop("_content_hash", None)
    state, is_current, current_bundle = _state_for(conn, job_id, r["report_id"])
    return {"report_id": r["report_id"], "job_id": job_id, "bundle_id": r["bundle_id"],
            "bundle": bundle_repo.payload(conn, r["bundle_id"]),
            "report_md": r["report_md"], "structured": structured, "profile_revision": r["profile_revision"],
            "report_version": r["report_version"], "created_at": r["created_at"],
            "report_state": state, "is_current": is_current, "current_bundle_id": current_bundle}

def list_for_job(conn, job_id: str) -> list[dict]:
    rows = conn.execute("""select report_id, bundle_id, profile_revision, report_version, created_at from deepdives
                           where job_id=? order by created_at desc, rowid desc""", (job_id,)).fetchall()
    return [dict(r) for r in rows]
