# src/where_my_job/store/bundles.py
from __future__ import annotations
import json
from ..clock import Clock, iso_utc
from ..errors import InvalidInput, ErrorItem
from ..ids import new_id, canonical_json
from . import evidence as ev_repo
from . import signals

BUNDLE_MAX_BYTES = 65536
EXCERPT_IN_BUNDLE = 4000
EVIDENCE_PAGE_MAX = 200

def _err(code: str, message: str, path: str) -> InvalidInput:
    return InvalidInput([ErrorItem(code, message, path)])

def _row(conn, bundle_id: str) -> dict | None:
    r = conn.execute("select * from evidence_bundles where bundle_id=?", (bundle_id,)).fetchone()
    if r is None:
        return None
    d = dict(r)
    d["evidence_ids"] = json.loads(d.pop("evidence_ids_json"))
    d["unknowns"] = json.loads(d.pop("unknowns_json"))
    return d

def _dedup(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))

def create(conn, clock: Clock, *, job_id: str, run_id: str | None, evidence_ids: list[str],
           acquisition_state: str, unknowns: list[str]) -> str:
    if acquisition_state not in ("complete", "partial"):
        raise ValueError("acquisition_state 只能是 complete 或 partial")
    r = conn.execute("select current_sighting_id from jobs where job_id=?", (job_id,)).fetchone()
    if r is None:
        raise _err("NOT_FOUND", f"岗位不存在: {job_id}", "$.job_id")
    if r[0] is None:
        raise _err("NOT_FOUND", "岗位没有可绑定的事实观察", "$.job_id")
    bid = new_id("bundle", clock.now())
    conn.execute("""insert into evidence_bundles(bundle_id, job_id, run_id, parent_bundle_id, evidence_ids_json,
                    fact_sighting_id, acquisition_state, unknowns_json, bundle_version, created_at)
                    values (?,?,?,NULL,?,?,?,?,1,?)""",
                 (bid, job_id, run_id, canonical_json(_dedup(evidence_ids)), r[0], acquisition_state,
                  canonical_json(list(unknowns)), iso_utc(clock.now())))
    return bid

def derive(conn, clock: Clock, *, base_bundle_id: str, extra_evidence_ids: list[str]) -> str:
    """基于旧包生成新不可变版本：旧清单 + 增补；acquisition_state、fact_sighting_id、unknowns 继承。"""
    base = _row(conn, base_bundle_id)
    if base is None:
        raise _err("NOT_FOUND", f"证据包不存在: {base_bundle_id}", "$.bundle_id")
    merged = _dedup(list(base["evidence_ids"]) + list(extra_evidence_ids))
    bid = new_id("bundle", clock.now())
    conn.execute("""insert into evidence_bundles(bundle_id, job_id, run_id, parent_bundle_id, evidence_ids_json,
                    fact_sighting_id, acquisition_state, unknowns_json, bundle_version, created_at)
                    values (?,?,?,?,?,?,?,?,?,?)""",
                 (bid, base["job_id"], base["run_id"], base_bundle_id, canonical_json(merged), base["fact_sighting_id"],
                  base["acquisition_state"], canonical_json(base["unknowns"]), base["bundle_version"] + 1,
                  iso_utc(clock.now())))
    return bid

def get(conn, bundle_id: str) -> dict | None:
    return _row(conn, bundle_id)

def current_for_job(conn, job_id: str) -> dict | None:
    r = conn.execute("""select bundle_id from evidence_bundles where job_id=?
                        order by created_at desc, bundle_version desc, rowid desc limit 1""", (job_id,)).fetchone()
    return _row(conn, r[0]) if r else None

def ids_for_job(conn, job_id: str) -> frozenset[str]:
    return frozenset(r[0] for r in conn.execute("select bundle_id from evidence_bundles where job_id=?", (job_id,)))

def _bundle_fact(conn, bundle):
    from ..errors import InvalidInput, ErrorItem
    identity = conn.execute("""select job_id, source, source_job_id, first_seen_at, last_seen_at,
        seen_run_count, hit_count from jobs where job_id=?""", (bundle["job_id"],)).fetchone()
    if identity is None:
        raise InvalidInput([ErrorItem("NOT_FOUND", "岗位不存在", "$.job_id")])
    sid = bundle["fact_sighting_id"]
    sighting = conn.execute("""select fact_json, content_hash from sightings
        where observation_id=? and job_id=?""", (sid, bundle["job_id"])).fetchone()
    if sighting is None:
        raise InvalidInput([ErrorItem("NOT_FOUND", "证据包绑定的事实不可用", "$.fact_sighting_id")])
    snapshot = json.loads(sighting["fact_json"])
    keys = ("title", "company_name", "city", "district", "salary_text", "salary_lo", "salary_hi",
            "salary_currency", "salary_period", "pay_months", "exp", "degree")
    fact = {key: snapshot.get(key) for key in keys}
    fact.update(job_id=identity["job_id"], job_url=("https://www.zhipin.com/job_detail/" + identity["source_job_id"] + ".html") if identity["source"] == "boss" else None,
                skills_json=canonical_json(snapshot.get("skills", [])), fact_revision=sighting["content_hash"],
                fact_sighting_id=sid)
    observations = {key: identity[key] for key in ("first_seen_at", "last_seen_at", "seen_run_count", "hit_count")}
    return fact, observations

def fit_payload(out):
    from ..errors import InvalidInput, ErrorItem
    def size():
        return len(json.dumps(out, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    def compact(value):
        if isinstance(value, str):
            return value[:1000]
        if isinstance(value, list):
            return [compact(x) for x in value[:32]]
        if isinstance(value, dict):
            return {k: compact(v) for k, v in value.items()}
        return value
    out["evidence_total"] = len(out["evidence"])
    out["next_evidence_offset"] = None
    out["truncated"] = bool(out.get("truncated", False))
    for item in out["evidence"]:
        excerpt = item.get("excerpt") or ""
        if len(excerpt) > EXCERPT_IN_BUNDLE:
            item["excerpt"] = excerpt[:EXCERPT_IN_BUNDLE]
            item["excerpt_truncated"] = True
            out["truncated"] = True
        if item.get("structured_truncated"):
            out["truncated"] = True
    while size() > BUNDLE_MAX_BYTES and out["evidence"]:
        out["evidence"].pop()
        out["next_evidence_offset"] = len(out["evidence"])
        out["truncated"] = True
    if size() > BUNDLE_MAX_BYTES:
        for key in ("fact", "signals", "unknowns"):
            out[key] = compact(out[key])
        out["summary_truncated"] = True
        out["truncated"] = True
    if size() > BUNDLE_MAX_BYTES:
        out["fact"] = {k: out["fact"].get(k) for k in
                       ("job_id", "job_url", "fact_revision", "fact_sighting_id", "title")}
        out["signals"] = {}
        out["unknowns"] = ["摘要超出输出上限，请按 bundle 分页读取证据"]
    if size() > BUNDLE_MAX_BYTES:
        raise InvalidInput([ErrorItem("SEMANTIC_INVALID", "证据包元数据超过输出上限", "$.bundle_id")])
    return out

def payload(conn, bundle_id: str) -> dict:
    """给 agent 的证据包：冻结事实 + 公开证据 + 信号 + 未知项；序列化 ≤ 65536 字节。调用方持有读事务。"""
    b = _row(conn, bundle_id)
    if b is None:
        raise _err("NOT_FOUND", f"证据包不存在: {bundle_id}", "$.bundle_id")
    fact, observations = _bundle_fact(conn, b)
    as_of = conn.execute("select wmj_as_of()").fetchone()[0]
    items: list[dict] = []
    detail_struct: dict = {}
    company_struct: dict = {}
    company_captured = None
    for eid in b["evidence_ids"]:
        pub = ev_repo.get_public(conn, eid)
        if pub is None:
            items.append({"evidence_id": eid, "missing": True})
            continue
        if pub["kind"] == "job_detail_page":
            detail_struct = pub["structured"]
        elif pub["kind"] == "company_page":
            company_struct = pub["structured"]
            company_captured = pub["captured_at"]
        items.append(pub)
    sig = {
        "observation_as_of": as_of,
        "observation_span": signals.observation_span(first=observations["first_seen_at"], last=observations["last_seen_at"],
                                                     hits=observations["hit_count"], runs=observations["seen_run_count"],
                                                     as_of=as_of),
        "company_counts": signals.count_ratio(boss_count=company_struct.get("boss_count"),
                                              job_count=company_struct.get("job_count"),
                                              boss_count_raw=company_struct.get("boss_count_raw"),
                                              job_count_raw=company_struct.get("job_count_raw"),
                                              snapshot_at=company_captured),
        "list_detail_diff": signals.list_detail_diff(fact, detail_struct),
        "up_date": signals.up_date_raw(detail_struct),
    }
    out = {"bundle_id": b["bundle_id"], "job_id": b["job_id"], "bundle_version": b["bundle_version"],
           "parent_bundle_id": b["parent_bundle_id"], "acquisition_state": b["acquisition_state"],
           "unknowns": list(b["unknowns"]), "fact": fact, "evidence": items, "signals": sig,
           "created_at": b["created_at"], "truncated": False}
    return fit_payload(out)

def evidence_page(conn, bundle_id: str, *, limit: int, offset: int) -> dict:
    """按包内顺序分页读取公开证据；丢失的证据保留占位，offset 稳定。调用方持有读事务。"""
    if type(limit) is not int or not (1 <= limit <= EVIDENCE_PAGE_MAX) or type(offset) is not int or offset < 0:
        raise _err("SEMANTIC_INVALID", f"limit 须在 1..{EVIDENCE_PAGE_MAX}，offset >= 0", "$.limit")
    row = conn.execute("select evidence_ids_json from evidence_bundles where bundle_id=?", (bundle_id,)).fetchone()
    if row is None:
        raise _err("NOT_FOUND", f"证据包不存在: {bundle_id}", "$.bundle_id")
    total = conn.execute("select json_array_length(?)", (row[0],)).fetchone()[0]
    rows = conn.execute("""select je.value from evidence_bundles bb, json_each(bb.evidence_ids_json) je
                           where bb.bundle_id=? order by cast(je.key as integer) limit ? offset ?""",
                        (bundle_id, limit, offset)).fetchall()
    items = [ev_repo.get_public(conn, r[0]) or {"evidence_id": r[0], "missing": True} for r in rows]
    return {"bundle_id": bundle_id, "items": items, "total": total, "offset": offset, "limit": limit,
            "truncated": offset + len(items) < total}
