from __future__ import annotations
import fcntl, json, os, sqlite3
from ..clock import Clock, iso_utc
from ..errors import EnvError
from ..ids import new_id, sha256_json, canonical_json
from . import db

INTERRUPTED_MESSAGE = "前次进程在任务完成前退出"

def create(conn, clock: Clock, *, kind: str, config: dict, planned: int,
           parent_run_id: str | None = None, run_id: str | None = None) -> str:
    """底层插入。生产代码使用 create_owned。"""
    run_id = run_id or new_id("run", clock.now())
    conn.execute("""insert into runs(run_id, kind, status, parent_run_id, config_json, config_hash,
                    planned_count, completed_count, started_at) values (?,?,?,?,?,?,?,0,?)""",
                 (run_id, kind, "running", parent_run_id, canonical_json(config), sha256_json(config),
                  planned, iso_utc(clock.now())))
    return run_id

def _lock_path(lay, run_id: str):
    return lay.runs_dir / f"{run_id}.lock"

def create_owned(ctx, *, kind: str, config: dict, planned: int, parent_run_id: str | None = None) -> str:
    run_id = new_id("run", ctx.clock.now())
    path = _lock_path(ctx.home, run_id)
    try:
        ctx.home.runs_dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    except PermissionError as e:
        raise EnvError("PERMISSION_DENIED", f"无法创建运行锁: {e.strerror}") from e
    except OSError as e:
        raise EnvError("DISK_ERROR", f"无法创建运行锁: {e.strerror}") from e
    handle = os.fdopen(fd, "r+b")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        ctx.run_locks[run_id] = handle                    # 先持 OS 锁，再插入 run 行
        if ctx.conn.in_transaction:                       # 调用方事务内（02 match）：不 BEGIN、不 COMMIT
            try:
                create(ctx.conn, ctx.clock, kind=kind, config=config, planned=planned,
                       parent_run_id=parent_run_id, run_id=run_id)
            except sqlite3.Error as e:
                mapped = db.map_sqlite_error(e)
                if mapped is not None:
                    raise mapped from e
                raise
        else:                                             # 事务外（01 import、04 deepdive）：自带短 BEGIN IMMEDIATE/COMMIT
            with db.write_tx(ctx.conn):
                create(ctx.conn, ctx.clock, kind=kind, config=config, planned=planned,
                       parent_run_id=parent_run_id, run_id=run_id)
    except BaseException:
        ctx.run_locks.pop(run_id, None)
        handle.close()
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return run_id

def release_run_locks(ctx) -> None:
    for run_id, handle in list(ctx.run_locks.items()):
        try:
            try:
                row = ctx.conn.execute("select status from runs where run_id=?", (run_id,)).fetchone()
                terminal = row is None or row[0] != "running"
            except sqlite3.Error:
                terminal = False
            if terminal:
                try:
                    _lock_path(ctx.home, run_id).unlink()   # 仍持锁时删除，避免与恢复竞争
                except OSError:
                    pass
        finally:
            handle.close()
            ctx.run_locks.pop(run_id, None)

def recover_orphans(ctx) -> list[str]:
    recovered: list[str] = []
    running = [r[0] for r in ctx.conn.execute("select run_id from runs where status='running' order by started_at, run_id")]
    for run_id in running:
        if run_id in ctx.run_locks:
            continue
        path = _lock_path(ctx.home, run_id)
        try:
            fd = os.open(path, os.O_RDWR)
        except FileNotFoundError:
            ctx.warnings.append(f"run {run_id} 仍为 running 但缺少所有者锁文件，未自动判定中断")
            continue
        except OSError as e:
            ctx.warnings.append(f"run {run_id} 的所有者锁无法打开（{e.strerror}），保持原状")
            continue
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue                                  # 所有者进程仍在运行
            changed = False
            with db.write_tx(ctx.conn):
                row = ctx.conn.execute("select status, summary_json from runs where run_id=?", (run_id,)).fetchone()
                if row is not None and row["status"] == "running":
                    summary = json.loads(row["summary_json"] or "{}")
                    summary["interrupted"] = True
                    now = iso_utc(ctx.clock.now())
                    ctx.conn.execute("update runs set status='failed', summary_json=?, ended_at=? where run_id=?",
                                     (canonical_json(summary), now, run_id))
                    ctx.conn.execute("""update run_tasks set status='failed', failure_code='INTERNAL',
                                        failure_message=?, ended_at=?
                                        where run_id=? and status in ('planned','running')""",
                                     (INTERRUPTED_MESSAGE, now, run_id))
                    changed = True
            if changed:
                recovered.append(run_id)
                try:
                    path.unlink()
                except OSError:
                    pass
        finally:
            os.close(fd)                                  # 提交之后才释放锁
    return recovered

def add_task(conn, clock: Clock, run_id: str, *, task_key: str, query: dict, status: str = "running") -> str:
    task_id = new_id("task", clock.now())
    conn.execute("""insert into run_tasks(task_id, run_id, task_key, query_json, status, started_at)
                    values (?,?,?,?,?,?)""",
                 (task_id, run_id, task_key, canonical_json(query), status, iso_utc(clock.now())))
    return task_id

def finish_task(conn, clock: Clock, task_id: str, *, status: str, failure_code: str | None = None,
                failure_message: str | None = None, response_key: str | None = None) -> None:
    conn.execute("""update run_tasks set status=?, failure_code=?, failure_message=?, response_key=?, ended_at=?
                    where task_id=?""",
                 (status, failure_code, failure_message, response_key, iso_utc(clock.now()), task_id))

def update_progress(conn, run_id: str, *, completed: int, summary: dict) -> None:
    conn.execute("update runs set completed_count=?, summary_json=? where run_id=?",
                 (completed, canonical_json(summary), run_id))

def finish(conn, clock: Clock, run_id: str, *, status: str, completed: int, summary: dict) -> None:
    conn.execute("update runs set status=?, completed_count=?, summary_json=?, ended_at=? where run_id=?",
                 (status, completed, canonical_json(summary), iso_utc(clock.now()), run_id))

def get(conn, run_id: str):
    return conn.execute("select * from v_runs where run_id=?", (run_id,)).fetchone()

def add_planned_tasks(conn, clock: Clock, run_id: str, tasks: list[tuple[str, dict]]) -> dict[str, str]:
    """一次写入全部计划任务（status=planned），返回 task_key → task_id。调用方持 write_tx。"""
    out: dict[str, str] = {}
    for task_key, query in tasks:
        out[task_key] = add_task(conn, clock, run_id, task_key=task_key, query=query, status="planned")
    return out

def merge_task_query(conn, task_id: str, patch: dict) -> None:
    row = conn.execute("select query_json from run_tasks where task_id=?", (task_id,)).fetchone()
    merged = {**json.loads(row[0]), **patch}
    conn.execute("update run_tasks set query_json=? where task_id=?", (canonical_json(merged), task_id))

def skip_planned(conn, clock: Clock, run_id: str, reason: str, task_ids: list[str] | None = None) -> int:
    """把仍为 planned 的任务标 skipped；reason 是固定原因码（no_more_results / stopped_after_failure / has_more_unknown）。"""
    params: list = [iso_utc(clock.now()), reason, run_id]
    where = "run_id=? and status='planned'"
    if task_ids is not None:
        if not task_ids:
            return 0
        where += f" and task_id in ({','.join('?' * len(task_ids))})"
        params += task_ids
    cur = conn.execute(f"update run_tasks set status='skipped', failure_code=NULL, failure_message=?, ended_at=? where {where}",
                       [reason, params[0]] + params[2:])
    return cur.rowcount
