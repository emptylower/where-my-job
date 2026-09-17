# tests/helpers/evidence_seed.py
"""测试用：直接写岗位、cli 来源的详情页/公司页证据与站外证据，模拟子计划 05 的采集结果。"""
from __future__ import annotations
from datetime import timedelta
from tests.conftest import load_fixture
from where_my_job.clock import parse_iso
from where_my_job.store import db, runs, jobs, companies, sightings, evidence
from where_my_job.normalize.legacy import map_legacy_record

def seed_job(conn, clock, job_id: str, *, company_id: str | None = None, fixture_index: int = 0) -> str:
    """用 legacy fixture 第 fixture_index 条记录建岗位并写一条观察（观察时间 = clock.now() - 3 天）。返回 observation_id。"""
    rec = dict(load_fixture("legacy/合肥_AI产品经理.json")["jobs"][fixture_index])
    enc = job_id.split(":", 1)[1]
    rec["encrypt_job_id"] = enc
    rec["job_link"] = f"https://www.zhipin.com/job_detail/{enc}.html"
    brand = company_id.split(":", 1)[1] if company_id else ""
    rec["encrypt_brand_id"] = brand
    rec["company_link"] = f"https://www.zhipin.com/gongsi/{brand}.html" if brand else ""
    m = map_legacy_record(rec)
    file_sha = (enc.encode().hex() + "0" * 64)[:64]
    with db.write_tx(conn):
        run_id = runs.create(conn, clock, kind="import", config={"seed": job_id}, planned=1)
        task_id = runs.add_task(conn, clock, run_id, task_key=f"seed:{job_id}:{clock.now().isoformat()}", query={})
        if company_id:
            companies.ensure(conn, clock, company_id, "boss", brand, m.company_name)
        jobs.ensure(conn, clock, m.job_id, "boss", m.source_job_id, m.legacy_job_id, company_id)
        obs = sightings.insert(conn, clock, job_id=m.job_id, run_id=run_id, task_id=task_id,
                               file_sha256=file_sha, item_index=int(clock.now().timestamp()) * 10 + fixture_index,
                               page=None, observed_at=clock.now() - timedelta(days=3), observed_at_raw=None,
                               time_precision="file_snapshot", tz_assumption=None, raw_kind="legacy_mapped",
                               raw=m.raw_private, fact=m.fact)
        jobs.refresh_current(conn, clock, m.job_id)
        runs.finish_task(conn, clock, task_id, status="ok")
        runs.finish(conn, clock, run_id, status="ok", completed=1, summary={})
    return obs

def seed_cli_row(conn, clock, fixture: str, *, job_id: str | None, company_id: str | None, key: str, **over) -> str:
    row = dict(load_fixture(f"evidence/{fixture}"))
    row.update(over)
    with db.write_tx(conn):
        run_id = runs.create(conn, clock, kind="deepdive", config={"seed": key}, planned=1)
        eid = evidence.insert_cli(conn, clock, job_id=job_id, company_id=company_id, kind=row["kind"], url=row["url"],
                                  captured_at=parse_iso(row["captured_at"]), excerpt=row["excerpt"],
                                  full_text=row.get("full_text"), structured=row.get("structured") or {},
                                  parser_version=row["parser_version"], completeness=row["completeness"],
                                  run_id=run_id, idempotency_key=key)
        runs.finish(conn, clock, run_id, status="ok", completed=1, summary={})
    return eid

def seed_detail(conn, clock, job_id: str, **over) -> str:
    return seed_cli_row(conn, clock, "detail_page_row.json", job_id=job_id, company_id=None,
                        key=f"seed-detail-{job_id}-{over.get('captured_at', '')}-{over.get('completeness', '')}", **over)

def seed_company_page(conn, clock, company_id: str, **over) -> str:
    return seed_cli_row(conn, clock, "company_page_row.json", job_id=None, company_id=company_id,
                        key=f"seed-company-{company_id}-{over.get('captured_at', '')}-{over.get('completeness', '')}", **over)

def seed_web(conn, clock, job_id: str, key: str, **over) -> str:
    obj = dict(load_fixture("evidence/web_page.json"))
    obj.update(job_id=job_id, idempotency_key=key)
    obj.update(over)
    with db.write_tx(conn):
        eid, _ = evidence.insert_external(conn, clock, obj, origin="agent")
    return eid
