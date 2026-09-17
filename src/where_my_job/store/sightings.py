from __future__ import annotations
from datetime import datetime
from ..clock import Clock, iso_utc
from ..ids import new_id, canonical_json, sha256_json
from ..normalize.fact import Fact, fact_hash

def insert(conn, clock: Clock, *, job_id: str, run_id: str, task_id: str, item_index: int, page: int | None,
           observed_at: datetime | None, observed_at_raw: str | None, time_precision: str,
           tz_assumption: str | None, raw_kind: str, raw: dict | None, fact: Fact,
           response_key: str | None = None, file_sha256: str | None = None) -> str:
    obs_id = new_id("obs", clock.now())
    conn.execute("""insert into sightings(observation_id, job_id, run_id, task_id, response_key, file_sha256,
                    item_index, page, observed_at, observed_at_raw, time_precision, tz_assumption, raw_kind,
                    raw_json, fact_json, content_hash, raw_hash, created_at)
                    values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (obs_id, job_id, run_id, task_id, response_key, file_sha256, item_index, page,
                  iso_utc(observed_at) if observed_at is not None else None, observed_at_raw, time_precision,
                  tz_assumption, raw_kind,
                  canonical_json(raw) if raw is not None else None, canonical_json(fact.to_json()),
                  fact_hash(fact), sha256_json(raw) if raw is not None else None, iso_utc(clock.now())))
    return obs_id

def exists_file_key(conn, file_sha256: str, item_index: int) -> bool:
    return conn.execute("select 1 from sightings where file_sha256=? and item_index=?",
                        (file_sha256, item_index)).fetchone() is not None

def exists_capture_key(conn, task_id: str, response_key: str, item_index: int) -> bool:
    return conn.execute("select 1 from sightings where task_id=? and response_key=? and item_index=?",
                        (task_id, response_key, item_index)).fetchone() is not None

def prune_raw_before(conn, clock: Clock, before_utc: str) -> int:
    """观察时间未知（NULL）的原文不按时点清理。"""
    cur = conn.execute("""update sightings set raw_json=NULL, raw_pruned_at=?
                          where observed_at < ? and raw_json is not null""", (iso_utc(clock.now()), before_utc))
    return cur.rowcount

def count_raw_before(conn, before_utc: str) -> int:
    return conn.execute("select count(*) from sightings where observed_at < ? and raw_json is not null",
                        (before_utc,)).fetchone()[0]
