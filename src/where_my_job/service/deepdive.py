# src/where_my_job/service/deepdive.py
from __future__ import annotations
from dataclasses import dataclass, field
from ..errors import InvalidInput, EnvError, Partial, WmjError, ErrorItem
from ..store import db, runs, jobs as job_repo, bundles as bundle_repo, evidence as ev_repo
from .bootstrap import with_context
from .context import Context
from .online_gate import require_online_enabled

@dataclass
class AcquisitionResult:
    run_id: str
    detail_evidence_id: str | None
    company_evidence_id: str | None
    acquisition_state: str                 # 'complete' | 'partial'
    unknowns: list[str] = field(default_factory=list)
    blocked: WmjError | None = None        # 风控/冷却：保存已得证据后抛出，退出 3
    failure: WmjError | None = None        # 其它失败：有已存证据时以 PARTIAL_RESULT 抛出，退出 4

def acquire(ctx: Context, job_id: str, *, skip_company: bool) -> AcquisitionResult:
    from .deepdive_online import acquire as online_acquire
    return online_acquire(ctx, job_id, skip_company=skip_company)

_acquire = acquire

def derive_completeness(ctx: Context, *, detail_id: str | None, company_evidence_id: str | None,
                        skip_company: bool, company_known: bool, cached: bool) -> tuple[str, list[str]]:
    """按已存证据推导完整度；调用方持有读事务。"""
    unknowns: list[str] = []

    def page_ok(eid: str, label: str) -> bool:
        row = ev_repo.get_public(ctx.conn, eid)
        if row is None:
            unknowns.append(f"{label}: 证据记录缺失")
            return False
        ok = True
        if row["completeness"] != "complete":
            unknowns.append(f"{label}: completeness={row['completeness']}")
            ok = False
        if ev_repo.structured_of(ctx.conn, eid).get("text_truncated") is True:
            unknowns.append(f"{label}: 正文截断")
            ok = False
        return ok

    if detail_id is None:
        unknowns.append("job_detail_page: 未取得")
        detail_ok = False
    else:
        detail_ok = page_ok(detail_id, "job_detail_page")
    if skip_company:
        unknowns.append("company_page: 按 --skip-company 未采集")
        company_ok = False
    elif not company_known:
        unknowns.append("company_page: 岗位无已核实公司身份")
        company_ok = False
    elif company_evidence_id is None:
        unknowns.append("company_page: 无缓存证据" if cached else "company_page: 未取得")
        company_ok = False
    else:
        company_ok = page_ok(company_evidence_id, "company_page")
    return ("complete" if detail_ok and company_ok else "partial"), unknowns

def _cached(ctx: Context, job_id: str, skip_company: bool) -> AcquisitionResult:
    with db.read_tx(ctx.conn):
        detail = ev_repo.latest_cli(ctx.conn, job_id=job_id, kind="job_detail_page")
        company_id = ctx.conn.execute("select company_id from jobs where job_id=?", (job_id,)).fetchone()[0]
        company = None
        if detail is not None and not skip_company and company_id:
            company = ev_repo.latest_cli(ctx.conn, company_id=company_id, kind="company_page")
    if detail is None:
        raise InvalidInput([ErrorItem("NOT_FOUND", "该岗位没有缓存的详情页证据；去掉 --cached 进行在线采集", "$.cached")])
    run_id = runs.create_owned(ctx, kind="deepdive",
                               config={"job_id": job_id, "cached": True, "skip_company": skip_company}, planned=0)
    return AcquisitionResult(run_id=run_id, detail_evidence_id=detail["evidence_id"],
                             company_evidence_id=company["evidence_id"] if company else None,
                             acquisition_state="complete")

def run(ctx: Context, job_id: str, *, cached: bool, skip_company: bool) -> tuple[dict, str]:
    if not job_repo.exists(ctx.conn, job_id):
        raise InvalidInput([ErrorItem("NOT_FOUND", f"岗位不存在: {job_id}", "$.job_id")])
    if not cached:
        require_online_enabled(ctx)
        result = _acquire(ctx, job_id, skip_company=skip_company)
    else:
        result = _cached(ctx, job_id, skip_company)
    finished = False
    bundle_id = None
    state = "partial"
    try:
        ids = [e for e in (result.detail_evidence_id, result.company_evidence_id) if e]
        if not ids:
            err = result.blocked or result.failure or EnvError("CAPTURE_FAILED", "未取得可验证的页面响应，已停止")
            with db.write_tx(ctx.conn):
                runs.finish(ctx.conn, ctx.clock, result.run_id, status="blocked" if result.blocked else "failed",
                            completed=0, summary={"bundle_id": None, "acquisition_state": None, "error_code": err.code})
            finished = True
            err.run_id = result.run_id
            raise err
        with db.read_tx(ctx.conn):
            company_known = ctx.conn.execute("select company_id from jobs where job_id=?", (job_id,)).fetchone()[0] is not None
            state, derived = derive_completeness(ctx, detail_id=result.detail_evidence_id,
                                                 company_evidence_id=result.company_evidence_id,
                                                 skip_company=skip_company, company_known=company_known, cached=cached)
        if result.acquisition_state == "partial" or result.blocked or result.failure:
            state = "partial"
        unknowns = list(dict.fromkeys([*result.unknowns, *derived]))
        status = "blocked" if result.blocked else ("partial" if result.failure else "ok")
        with db.write_tx(ctx.conn):
            bundle_id = bundle_repo.create(ctx.conn, ctx.clock, job_id=job_id, run_id=result.run_id, evidence_ids=ids,
                                           acquisition_state=state, unknowns=unknowns)
            runs.finish(ctx.conn, ctx.clock, result.run_id, status=status, completed=len(ids),
                        summary={"bundle_id": bundle_id, "acquisition_state": state})
        finished = True
    finally:
        if not finished:
            try:
                with db.write_tx(ctx.conn):
                    runs.finish(ctx.conn, ctx.clock, result.run_id, status="failed", completed=0,
                                summary={"error_code": "INTERNAL"})
            except Exception:
                pass
    with db.read_tx(ctx.conn):
        payload = bundle_repo.payload(ctx.conn, bundle_id)
        report_state = ctx.conn.execute("select report_state from v_jobs where job_id=?", (job_id,)).fetchone()[0]
    data = {"bundle_id": bundle_id, "bundle": payload, "report_state": report_state, "cached": cached,
            "acquisition_state": state}
    if result.blocked is not None:
        err = result.blocked
        err.data = dict(err.data, **data)
        err.run_id = result.run_id
        raise err
    if result.failure is not None:
        err = result.failure if isinstance(result.failure, Partial) else Partial(
            "PARTIAL_RESULT", "已保存部分证据，但采集未完成", data={"failure_code": result.failure.code})
        err.data = dict(err.data, **data)
        err.run_id = result.run_id
        raise err
    return data, result.run_id

def register(sub, set_handler):
    p = sub.add_parser("deepdive", help="点名岗位：采集两页或读取缓存，创建证据包（analysis_pending）")
    p.add_argument("job_id")
    p.add_argument("--cached", action="store_true")
    p.add_argument("--skip-company", action="store_true")
    set_handler(p, "deepdive", lambda ns, w: with_context(
        ns, w, lambda ctx: run(ctx, ns.job_id, cached=ns.cached, skip_company=ns.skip_company), write=True))
