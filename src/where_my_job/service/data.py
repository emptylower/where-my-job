# src/where_my_job/service/data.py
from __future__ import annotations
from ..clock import parse_iso, iso_utc
from ..errors import InvalidInput, Partial, ErrorItem
from .. import paths
from ..store import db, sightings
from .bootstrap import with_context
from .context import Context

# 删除顺序：先子表后父表；网络策略状态永不删；共享公司身份不删（可能被其他岗位引用）。
_JOB_SCOPED = [
    ("events", "subject_kind='application' and subject_id in (select application_id from applications where job_id=?)"),
    ("events", "subject_kind='job' and subject_id=?"),
    ("applications", "job_id=?"),
    ("job_attrs", "job_id=?"),
    ("match_results", "job_id=?"),
    ("deepdives", "job_id=?"),
    ("evidence_bundles", "job_id=?"),
    ("evidence", "job_id=?"),
    ("sightings", "job_id=?"),
    ("jobs", "job_id=?"),
]
_ALL_ORDER = ["events", "applications", "stream_registry", "job_attrs", "match_results", "deepdives",
              "evidence_bundles", "evidence", "sightings", "run_tasks", "runs", "jobs", "companies"]
# 内置流声明（子计划 03 迁移注册的 applications）不是用户业务数据，--all 只删 custom.* 声明
_ALL_WHERE = {"stream_registry": "stream like 'custom.%'"}

def _artifacts(ctx: Context, dry_run: bool) -> tuple[dict, dict]:
    return (paths.invalidate_managed_outputs(ctx.home, dry_run=dry_run),
            paths.clear_migration_backups(ctx.home, dry_run=dry_run))

def _complete(ctx: Context, data: dict) -> dict:
    outputs, backups = _artifacts(ctx, dry_run=False)
    data.update(managed_outputs=outputs, migration_backups=backups, policy_state_kept=True)
    leftovers = outputs["kept_modified"] + outputs["failed"] + backups["failed"]
    if leftovers:
        raise Partial("PARTIAL_RESULT", "数据库已清理，但以下派生文件未清理：" + ", ".join(leftovers), data=data)
    return data

def _preview(ctx: Context, data: dict) -> dict:
    outputs, backups = _artifacts(ctx, dry_run=True)
    data.update(dry_run=True, managed_outputs=outputs, migration_backups=backups, policy_state_kept=True)
    return data

def _delete_events(c, ev_ids: list[str]) -> None:
    """events 纠错链自引用：反复删除“没有后继”的事件直到清空。"""
    remaining = set(ev_ids)
    while remaining:
        tails = [e for e in remaining
                 if c.execute("select 1 from events where corrected_event_id=?", (e,)).fetchone() is None]
        if not tails:
            raise RuntimeError("events correction chain cycle")
        for e in tails:
            c.execute("delete from events where event_id=?", (e,))
            remaining.discard(e)

def delete(ctx: Context, job_id: str | None, all_: bool, dry_run: bool) -> dict:
    if bool(job_id) == all_:
        raise InvalidInput([ErrorItem("SCHEMA_INVALID", "--job ID 与 --all 二选一", "$.target")])
    c = ctx.conn
    counts: dict[str, int] = {}
    if job_id:
        if c.execute("select 1 from jobs where job_id=?", (job_id,)).fetchone() is None:
            raise InvalidInput([ErrorItem("NOT_FOUND", f"岗位不存在: {job_id}", "$.job")])
        for table, where in _JOB_SCOPED:
            counts[table] = counts.get(table, 0) + c.execute(f"select count(*) from {table} where {where}", (job_id,)).fetchone()[0]
        if dry_run:
            return _preview(ctx, {"would_delete": counts})
        with db.write_tx(c):
            ev_ids = [r[0] for r in c.execute(
                """select event_id from events where (subject_kind='job' and subject_id=?)
                   or (subject_kind='application' and subject_id in (select application_id from applications where job_id=?))""",
                (job_id, job_id))]
            _delete_events(c, ev_ids)
            for table, where in _JOB_SCOPED[2:]:
                c.execute(f"delete from {table} where {where}", (job_id,))
        return _complete(ctx, {"deleted": counts})
    for t in _ALL_ORDER:
        counts[t] = c.execute(f"select count(*) from {t} where {_ALL_WHERE.get(t, '1=1')}").fetchone()[0]
    if dry_run:
        return _preview(ctx, {"would_delete": counts})
    with db.write_tx(c):
        for t in _ALL_ORDER:
            c.execute(f"delete from {t} where {_ALL_WHERE.get(t, '1=1')}")
    return _complete(ctx, {"deleted": counts})

def prune(ctx: Context, raw_before: str, dry_run: bool) -> dict:
    try:
        before = iso_utc(parse_iso(raw_before))
    except (ValueError, OverflowError) as e:
        raise InvalidInput([ErrorItem("SCHEMA_INVALID", f"--raw-before 需要带时区的 ISO 时间: {e}", "$.raw_before")])
    c = ctx.conn
    n_s = sightings.count_raw_before(c, before)
    n_e = c.execute("select count(*) from evidence where captured_at < ? and full_text is not null", (before,)).fetchone()[0]
    if dry_run:
        return _preview(ctx, {"sightings_raw_to_prune": n_s, "evidence_text_to_prune": n_e, "before": before})
    with db.write_tx(c):
        ps = sightings.prune_raw_before(c, ctx.clock, before)
        pe = c.execute("update evidence set full_text=NULL, full_text_pruned_at=? where captured_at < ? and full_text is not null",
                       (iso_utc(ctx.clock.now()), before)).rowcount
    return _complete(ctx, {"sightings_raw_pruned": ps, "evidence_text_pruned": pe, "before": before})

def register(sub, set_handler):
    p = sub.add_parser("data", help="用户显式清理")
    s = p.add_subparsers(dest="data_cmd")
    s.required = True
    d = s.add_parser("delete")
    d.add_argument("--job")
    d.add_argument("--all", action="store_true")
    d.add_argument("--dry-run", action="store_true")
    set_handler(d, "data delete", lambda ns, w: with_context(
        ns, w, lambda ctx: delete(ctx, ns.job, ns.all, ns.dry_run), write=not ns.dry_run))
    r = s.add_parser("prune")
    r.add_argument("--raw-before", required=True)
    r.add_argument("--dry-run", action="store_true")
    set_handler(r, "data prune", lambda ns, w: with_context(
        ns, w, lambda ctx: prune(ctx, ns.raw_before, ns.dry_run), write=not ns.dry_run))
