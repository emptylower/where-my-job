from __future__ import annotations
from ..clock import Clock, iso_utc

def ensure(conn, clock: Clock, job_id: str, source: str, source_job_id: str,
           legacy_job_id: str | None, company_id: str | None) -> None:
    now = iso_utc(clock.now())
    conn.execute("""insert into jobs(job_id, source, source_job_id, legacy_job_id, company_id, created_at, updated_at)
                    values (?,?,?,?,?,?,?)
                    on conflict(job_id) do update set
                      legacy_job_id = coalesce(jobs.legacy_job_id, excluded.legacy_job_id),
                      company_id    = coalesce(jobs.company_id, excluded.company_id),
                      updated_at    = excluded.updated_at""",
                 (job_id, source, source_job_id, legacy_job_id, company_id, now, now))

def refresh_current(conn, clock: Clock, job_id: str) -> None:
    """按 (observed_at DESC NULLS LAST, 精度 DESC, observation_id ASC) 选最新有效观察；min/max 忽略未知时间。"""
    row = conn.execute("""select observation_id from sightings where job_id=?
                          order by observed_at desc nulls last,
                                   case time_precision when 'response' then 2 else 1 end desc,
                                   observation_id asc
                          limit 1""", (job_id,)).fetchone()
    agg = conn.execute("""select min(observed_at), max(observed_at), count(*), count(distinct run_id)
                          from sightings where job_id=?""", (job_id,)).fetchone()
    conn.execute("""update jobs set current_sighting_id=?, first_seen_at=?, last_seen_at=?, hit_count=?,
                    seen_run_count=?, updated_at=? where job_id=?""",
                 (row[0] if row else None, agg[0], agg[1], agg[2], agg[3], iso_utc(clock.now()), job_id))

def exists(conn, job_id: str) -> bool:
    return conn.execute("select 1 from jobs where job_id=?", (job_id,)).fetchone() is not None

def get_view(conn, job_id: str):
    return conn.execute("select * from v_jobs where job_id=?", (job_id,)).fetchone()
