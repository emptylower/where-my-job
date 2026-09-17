"""为需要数据库的命令打开 Layout + 连接 + Context；写命令先恢复遗留 run；结束时释放运行锁再关闭连接。"""
from __future__ import annotations
import sys
from ..paths import ensure_layout
from ..store import db, runs
from .context import Context

def with_context(ns, warnings: list[str], fn, *, write: bool = False):
    from ..cli import main as cli_main
    clock = cli_main.make_clock()
    lay = ensure_layout()
    conn = db.open_db(lay.db_path, clock=clock)
    ctx = Context(home=lay, clock=clock, conn=conn, warnings=warnings, stderr=sys.stderr)
    try:
        db.migrate(conn, lay, clock=clock)
        if write:
            recovered = runs.recover_orphans(ctx)
            if recovered:
                warnings.append(f"已把 {len(recovered)} 个前次中断的 run 标为 failed: {', '.join(recovered)}")
        from .profile_binding import bind_current_profile
        bind_current_profile(conn, lay, warnings)
        return fn(ctx)
    finally:
        try:
            runs.release_run_locks(ctx)
        finally:
            conn.close()
