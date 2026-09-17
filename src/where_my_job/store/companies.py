from __future__ import annotations
from ..clock import Clock, iso_utc

def ensure(conn, clock: Clock, company_id: str, source: str, source_company_id: str, name: str | None) -> None:
    """建身份占位；已有则只在 name 为空时补名字。"""
    now = iso_utc(clock.now())
    conn.execute("""insert into companies(company_id, source, source_company_id, name, created_at, updated_at)
                    values (?,?,?,?,?,?)
                    on conflict(company_id) do update set
                      name = coalesce(companies.name, excluded.name), updated_at = excluded.updated_at""",
                 (company_id, source, source_company_id, name, now, now))

def get(conn, company_id: str):
    return conn.execute("select * from companies where company_id=?", (company_id,)).fetchone()
