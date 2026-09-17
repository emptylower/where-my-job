# src/where_my_job/service/facts.py
"""把数据库事实快照装进 validate.Facts。"""
from __future__ import annotations
from ..validate import Facts
from ..store import streams as streams_store, applications as app_store

def build_facts(conn) -> Facts:
    job_ids = frozenset(r[0] for r in conn.execute("select job_id from jobs"))
    return Facts(job_ids=job_ids,
                 active_streams=streams_store.active_definitions(conn),
                 application_ids_by_job=app_store.ids_by_job(conn))
