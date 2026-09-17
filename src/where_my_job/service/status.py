from __future__ import annotations
import json, os
from datetime import timedelta
from ..clock import parse_iso
from ..errors import EnvError
from ..store import db
from .bootstrap import with_context
from .context import Context
from .staleness import version_warnings

BUDGET_24H = 80

def _network_lock_state(ctx) -> bool | None:
    """与在线入口共用同一把规范化浏览器锁判断占用；布局被链接篡改时如实报告未知（None），不猜。"""
    from ..policy.lock import is_locked
    try:
        return is_locked(ctx.home)
    except EnvError:
        return None

def _last_run(conn, kind: str, probe: bool | None = None) -> dict | None:
    """最近一次 run：按 started_at DESC、基表 rowid DESC 取一行，再读列；probe 按 config.probe 过滤。"""
    extra = ""
    if probe is True:
        extra = " and json_extract(config_json, '$.probe') = 1"
    elif probe is False:
        extra = " and coalesce(json_extract(config_json, '$.probe'), 0) = 0"
    row = conn.execute(f"select rowid from runs where kind=?{extra} order by started_at desc, rowid desc limit 1", (kind,)).fetchone()
    if row is None:
        return None
    r = conn.execute("select run_id, status, started_at, ended_at, completed_count, planned_count from runs where rowid=?",
                     (row[0],)).fetchone()
    return dict(r)

def run(ctx: Context) -> dict:
    run_cfg = version_warnings(ctx)
    c = ctx.conn
    with db.read_tx(c):
        one = lambda sql, *a: c.execute(sql, a).fetchone()[0]
        counts = {"jobs": one("select count(*) from jobs"), "sightings": one("select count(*) from sightings"),
                  "companies": one("select count(*) from companies"), "evidence": one("select count(*) from evidence"),
                  "reports": one("select count(*) from deepdives"), "events": one("select count(*) from events")}
        obs = c.execute("select min(observed_at), max(observed_at), "
                        "coalesce(sum(observed_at is null), 0) from sightings").fetchone()
        retention = {"policy": "no_expiry",
                     "raw_pruned_before": one("select max(observed_at) from sightings "
                                              "where raw_json is null and raw_pruned_at is not null"),
                     "last_prune_at": one("select max(raw_pruned_at) from sightings")}

        def last(kind):
            return _last_run(c, kind)

        running = [r[0] for r in c.execute("select run_id from runs where status='running' order by started_at, run_id")]
        states = {"missing": 0, "current": 0, "stale": 0}
        for state, n in c.execute("select match_state, count(*) from v_jobs group by match_state"):
            states[state] = n
        total = sum(states.values())
        if total == 0 or (states["missing"] and not states["stale"]):
            match_state = "missing"
        elif states["stale"]:
            match_state = "stale"
        else:
            match_state = "current"
        match_run = c.execute("select run_id from runs where kind='match' and status='ok' "
                              "order by started_at desc, rowid desc limit 1").fetchone()
        pending = one("""select count(*) from evidence_bundles b
                         where b.bundle_id = (select b2.bundle_id from evidence_bundles b2 where b2.job_id = b.job_id
                                              order by b2.created_at desc, b2.bundle_version desc, b2.rowid desc limit 1)
                           and not exists (select 1 from deepdives d where d.bundle_id = b.bundle_id)""")
        policy = c.execute("select cooldown_until, ledger_json from network_policy_state limit 1").fetchone()
        as_of = one("select wmj_as_of()")
    actions = 0
    if policy and policy["ledger_json"]:
        cutoff = ctx.clock.now() - timedelta(hours=24)
        actions = sum(1 for e in json.loads(policy["ledger_json"]) if parse_iso(e["at"]) >= cutoff)
    data = {
        "counts": counts,
        "observations": {"earliest": obs[0], "latest": obs[1], "unknown_time_count": obs[2]},
        "retention": retention,
        "runs": {"last_import": last("import"), "last_scan": _last_run(c, "scan", probe=False),
                 "last_probe": _last_run(c, "scan", probe=True), "last_deepdive": last("deepdive"),
                 "last_match": last("match"), "running": running},
        "match": {"current_run_id": match_run[0] if match_run else None, "state": match_state, "counts": states},
        "reports": {"pending_bundles": pending},
        "network": {"lock_held": _network_lock_state(ctx),
                    "cooldown_until": policy["cooldown_until"] if policy else None,
                    "actions_last_24h": actions, "budget_24h": BUDGET_24H},
        "db_size_bytes": os.path.getsize(ctx.home.db_path),
        "as_of": as_of,
    }
    data["match_input"] = ({"input_selection": run_cfg.get("input_selection", "latest"),
                            "input_snapshot_hash": run_cfg.get("input_snapshot_hash")} if run_cfg else None)
    return data

def register(sub, set_handler):
    p = sub.add_parser("status", help="本地状态：数据、评分、报告、任务、锁、预算、冷却（只读）")
    set_handler(p, "status", lambda ns, warnings: with_context(ns, warnings, run))
