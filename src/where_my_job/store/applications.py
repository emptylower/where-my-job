# src/where_my_job/store/applications.py
from __future__ import annotations
import sqlite3
from ..clock import Clock, iso_utc
from ..ids import new_id

def create(conn: sqlite3.Connection, clock: Clock, job_id: str) -> str:
    app_id = new_id("app", clock.now())
    conn.execute("insert into applications(application_id, job_id, created_at) values (?,?,?)", (app_id, job_id, iso_utc(clock.now())))
    return app_id

def get(conn, application_id: str) -> sqlite3.Row | None:
    return conn.execute("select * from applications where application_id=?", (application_id,)).fetchone()

def has_effective_applied(conn, application_id: str) -> bool:
    return conn.execute("""select 1 from v_effective_events where stream='applications' and subject_kind='application'
                           and subject_id=? and type='applied'""", (application_id,)).fetchone() is not None

def applied_at(conn, application_id: str) -> str | None:
    r = conn.execute("""select occurred_at from v_effective_events where stream='applications' and subject_kind='application'
                        and subject_id=? and type='applied'""", (application_id,)).fetchone()
    return r[0] if r else None

def ids_by_job(conn) -> dict[str, frozenset[str]]:
    """只含有有效 applied 的身份，供 Facts 使用。"""
    out: dict[str, set[str]] = {}
    for r in conn.execute("""select a.job_id, a.application_id from applications a
                             join v_effective_events ee on ee.subject_id=a.application_id and ee.stream='applications' and ee.type='applied'"""):
        out.setdefault(r[0], set()).add(r[1])
    return {k: frozenset(v) for k, v in out.items()}
