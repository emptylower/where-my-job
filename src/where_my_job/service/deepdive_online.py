# src/where_my_job/service/deepdive_online.py
"""deepdive 在线采集。两页各计一次受控动作；风险页不存证据；建 run 之后不抛异常，run 状态由 04 落定。"""
from __future__ import annotations
from ..adapter.cdp import CdpTransport
from ..adapter.detail import parse_job_detail, parse_company_page, PARSER_VERSION
from ..adapter.session import BrowserSession
from ..errors import Blocked, EnvError, InvalidInput, ErrorItem
from ..launcher.chrome import ChromeLauncher
from ..policy.gate import Gate
from ..public_messages import public_message
from ..store import db, runs, evidence as evidence_store
from . import network_run
from .deepdive import AcquisitionResult

def make_launcher(lay):
    return ChromeLauncher(lay)

def make_transport(ctx, verified):
    return CdpTransport.open(verified.ws_url)

def make_pacing(ctx):
    return None, None

def _stop(ctx, gate, st, task_id: str, read) -> None:
    """非 ok 读取：记任务、跳过剩余任务，然后以 Blocked 或 EnvError 结束 body。"""
    if read.kind == "blocked":
        blocked = gate.persist_block(st.run_id, reason_code=read.reason)   # 冷却先单独提交

        def bookkeep() -> None:
            with db.write_tx(ctx.conn):
                runs.finish_task(ctx.conn, ctx.clock, task_id, status="blocked", failure_code="RISK_DETECTED", failure_message=read.reason)
                runs.skip_planned(ctx.conn, ctx.clock, st.run_id, "stopped_after_failure")
        network_run.best_effort_write(ctx, bookkeep)
        raise blocked
    code = "UNAUTHENTICATED" if read.kind == "unauthenticated" else "CAPTURE_FAILED"
    with db.write_tx(ctx.conn):
        runs.finish_task(ctx.conn, ctx.clock, task_id, status="failed", failure_code=code, failure_message=read.reason)
        runs.skip_planned(ctx.conn, ctx.clock, st.run_id, "stopped_after_failure")
    raise EnvError(code, public_message(code))

def acquire(ctx, job_id: str, *, skip_company: bool) -> AcquisitionResult:
    job = ctx.conn.execute("select job_id, source_job_id, company_id from jobs where job_id=?", (job_id,)).fetchone()
    if job is None:
        raise InvalidInput([ErrorItem("NOT_FOUND", "岗位不存在", "$.job_id")])
    company_id = job["company_id"]
    do_company = (not skip_company) and company_id is not None
    lch = make_launcher(ctx.home)
    verified = lch.verify()
    lch.blank_check(verified)
    sleep, rng = make_pacing(ctx)
    gate = Gate(ctx, sleep=sleep, rng=rng)
    box: dict = {"unknowns": [], "detail": None, "company": None, "detail_complete": False, "company_complete": False}
    src_job = job["source_job_id"]
    src_company = company_id.split(":", 1)[1] if company_id else None

    def body(st):
        planned = [(f"job:{src_job}", {"kind": "job_detail_page"})]
        if do_company:
            planned.append((f"company:{src_company}", {"kind": "company_page"}))
        with db.write_tx(ctx.conn):
            ids = runs.add_planned_tasks(ctx.conn, ctx.clock, st.run_id, planned)
        transport = make_transport(ctx, verified)
        st.closers.append(transport.close)
        session = BrowserSession(transport)
        # ---- 详情页 ----
        gate.reserve("detail_page", st.run_id)
        read = session.open_job_detail(src_job)
        if read.kind != "ok":
            box["unknowns"].append(f"job_detail:{read.kind}")
            _stop(ctx, gate, st, ids[f"job:{src_job}"], read)
        parsed = parse_job_detail(read.extracted)
        with db.write_tx(ctx.conn):
            detail_id = evidence_store.insert_cli(
                ctx.conn, ctx.clock, job_id=job_id, company_id=None, kind="job_detail_page",
                url=f"https://www.zhipin.com/job_detail/{src_job}.html", captured_at=ctx.clock.now(),
                excerpt=(parsed.jd or "")[:2000], full_text=parsed.full_text, structured=parsed.structured,
                parser_version=PARSER_VERSION, completeness=parsed.completeness, run_id=st.run_id,
                idempotency_key=f"cli:{st.run_id}:job_detail:{job_id}")
            runs.finish_task(ctx.conn, ctx.clock, ids[f"job:{src_job}"], status="ok")
            runs.merge_task_query(ctx.conn, ids[f"job:{src_job}"], {"evidence_id": detail_id, "completeness": parsed.completeness})
        st.committed += 1
        st.completed += 1
        box.update(detail=detail_id, detail_complete=parsed.completeness == "complete")
        box["unknowns"] += [f"job_detail:{u}" for u in parsed.unknowns]
        if skip_company:
            box["unknowns"].append("company_page:skipped")
            return None
        if company_id is None:
            box["unknowns"].append("company_page:no_company_id")
            return None
        # ---- 公司页 ----
        task_id = ids[f"company:{src_company}"]
        gate.reserve("company_page", st.run_id)
        read = session.open_company(src_company)
        if read.kind != "ok":
            box["unknowns"].append(f"company_page:{read.kind}")
            _stop(ctx, gate, st, task_id, read)
        cp = parse_company_page(read.extracted)
        with db.write_tx(ctx.conn):
            company_ev = evidence_store.insert_cli(
                ctx.conn, ctx.clock, job_id=None, company_id=company_id, kind="company_page",
                url=f"https://www.zhipin.com/gongsi/{src_company}.html", captured_at=ctx.clock.now(),
                excerpt=(cp.full_text or "")[:2000], full_text=cp.full_text, structured=cp.structured,
                parser_version=PARSER_VERSION, completeness=cp.completeness, run_id=st.run_id,
                idempotency_key=f"cli:{st.run_id}:company_page:{company_id}")
            runs.finish_task(ctx.conn, ctx.clock, task_id, status="ok")
            runs.merge_task_query(ctx.conn, task_id, {"evidence_id": company_ev, "completeness": cp.completeness})
        st.committed += 1
        st.completed += 1
        box.update(company=company_ev, company_complete=cp.completeness == "complete")
        box["unknowns"] += [f"company_page:{u}" for u in cp.unknowns]
        return None

    out = network_run.execute(ctx, gate, actions=1 + int(do_company), kind="deepdive",
                              config={"job_id": job_id, "skip_company": skip_company}, body=body, finish=False)
    primary = out.primary
    complete = bool(box["detail"] and box["detail_complete"] and box["company"] and box["company_complete"])
    return AcquisitionResult(run_id=out.run_id, detail_evidence_id=box["detail"], company_evidence_id=box["company"],
                             acquisition_state="complete" if complete else "partial", unknowns=list(box["unknowns"]),
                             blocked=primary if isinstance(primary, Blocked) else None,
                             failure=primary if primary is not None and not isinstance(primary, Blocked) else None)
