import fcntl, json, os, sqlite3, stat, subprocess, sys
import pytest
from where_my_job import paths
from where_my_job.clock import SystemClock
from where_my_job.store import db, runs
from where_my_job.service.context import Context

def test_create_owned_holds_os_lock_and_release_cleans_up(ctx):
    run_id = runs.create_owned(ctx, kind="import", config={}, planned=1)
    lock = ctx.home.runs_dir / f"{run_id}.lock"
    assert lock.exists() and stat.S_IMODE(lock.stat().st_mode) == 0o600
    fd = os.open(lock, os.O_RDWR)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)
    with db.write_tx(ctx.conn):
        runs.finish(ctx.conn, ctx.clock, run_id, status="ok", completed=1, summary={})
    runs.release_run_locks(ctx)
    assert not lock.exists() and ctx.run_locks == {}

def test_release_keeps_lock_file_for_unfinished_run(ctx):
    run_id = runs.create_owned(ctx, kind="import", config={}, planned=1)
    runs.release_run_locks(ctx)
    assert (ctx.home.runs_dir / f"{run_id}.lock").exists() and ctx.run_locks == {}

def test_create_owned_outside_transaction_commits_its_own_insert(ctx):
    assert not ctx.conn.in_transaction
    run_id = runs.create_owned(ctx, kind="deepdive", config={}, planned=2)
    assert not ctx.conn.in_transaction and run_id in ctx.run_locks
    other = sqlite3.connect(str(ctx.home.db_path))
    try:
        assert other.execute("select status from runs where run_id=?", (run_id,)).fetchone()[0] == "running"
    finally:
        other.close()

def test_create_owned_inside_callers_transaction_neither_begins_nor_commits(ctx):
    created = []
    with pytest.raises(RuntimeError):
        with db.write_tx(ctx.conn):
            created.append(runs.create_owned(ctx, kind="match", config={}, planned=1))
            assert ctx.conn.in_transaction and created[0] in ctx.run_locks
            raise RuntimeError("caller aborts")
    run_id = created[0]
    assert ctx.conn.execute("select count(*) from runs where run_id=?", (run_id,)).fetchone()[0] == 0
    runs.release_run_locks(ctx)
    assert not (ctx.home.runs_dir / f"{run_id}.lock").exists() and ctx.run_locks == {}

@pytest.mark.parametrize("in_tx", [False, True])
def test_create_owned_insert_failure_releases_and_unlinks_lock(ctx, monkeypatch, in_tx):
    def boom(*args, **kwargs):
        raise sqlite3.IntegrityError("simulated insert failure")
    monkeypatch.setattr(runs, "create", boom)
    with pytest.raises(sqlite3.IntegrityError):
        if in_tx:
            with db.write_tx(ctx.conn):
                runs.create_owned(ctx, kind="match", config={}, planned=1)
        else:
            runs.create_owned(ctx, kind="deepdive", config={}, planned=1)
    assert ctx.run_locks == {} and list(ctx.home.runs_dir.glob("*.lock")) == []
    assert not ctx.conn.in_transaction

def test_recover_leaves_own_active_and_ownerless_runs(ctx):
    own = runs.create_owned(ctx, kind="import", config={}, planned=1)
    with db.write_tx(ctx.conn):
        ownerless = runs.create(ctx.conn, ctx.clock, kind="import", config={}, planned=1)
    assert runs.recover_orphans(ctx) == []
    statuses = {r[0]: r[1] for r in ctx.conn.execute("select run_id, status from runs")}
    assert statuses == {own: "running", ownerless: "running"}
    assert any("缺少所有者锁文件" in w for w in ctx.warnings)

CHILD = r'''
import os, sys
from where_my_job import paths
from where_my_job.clock import SystemClock
from where_my_job.store import db, runs
from where_my_job.service.context import Context
lay = paths.ensure_layout()
conn = db.open_db(lay.db_path)
db.migrate(conn, lay)
ctx = Context(home=lay, clock=SystemClock(), conn=conn)
with db.write_tx(conn):
    run_id = runs.create_owned(ctx, kind="import", config={}, planned=2)
    runs.add_task(conn, ctx.clock, run_id, task_key="000000:a.json", query={})
print(run_id, flush=True)
sys.stdin.readline()
os._exit(0)   # 模拟进程在 run 结束前退出：不写终态，由 OS 释放锁
'''

def test_two_process_recovery_only_after_owner_exits(tmp_path, monkeypatch):
    monkeypatch.setenv("WMJ_HOME", str(tmp_path / "h"))
    child = subprocess.Popen([sys.executable, "-c", CHILD], env=dict(os.environ), stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        run_id = child.stdout.readline().strip()
        assert run_id.startswith("run_"), child.stderr.read()
        lay = paths.ensure_layout()
        conn = db.open_db(lay.db_path)
        db.migrate(conn, lay)
        ctx = Context(home=lay, clock=SystemClock(), conn=conn)
        for _ in range(3):
            assert runs.recover_orphans(ctx) == []
        assert conn.execute("select status from runs where run_id=?", (run_id,)).fetchone()[0] == "running"
        child.stdin.write("\n"); child.stdin.flush()
        child.wait(timeout=30)
        assert runs.recover_orphans(ctx) == [run_id]
        row = conn.execute("select status, summary_json from runs where run_id=?", (run_id,)).fetchone()
        assert row["status"] == "failed" and json.loads(row["summary_json"])["interrupted"] is True
        task = conn.execute("select status, failure_code, failure_message from run_tasks where run_id=?", (run_id,)).fetchone()
        assert (task[0], task[1], task[2]) == ("failed", "INTERNAL", "前次进程在任务完成前退出")
        assert not (lay.runs_dir / f"{run_id}.lock").exists()
        assert runs.recover_orphans(ctx) == []
        conn.close()
    finally:
        if child.poll() is None:
            child.kill()
