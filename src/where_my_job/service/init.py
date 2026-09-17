from __future__ import annotations
import sys
from ..paths import ensure_layout
from ..store import db, runs
from .context import Context

def run_local(ns, warnings) -> dict:
    from ..cli import main as cli_main
    clock = cli_main.make_clock()
    lay = ensure_layout()
    caps = db.capabilities()
    conn = db.open_db(lay.db_path, clock=clock)
    ctx = Context(home=lay, clock=clock, conn=conn, warnings=warnings, stderr=sys.stderr)
    try:
        applied = db.migrate(conn, lay, clock=clock)
        recovered = runs.recover_orphans(ctx)
        version = conn.execute("select max(version) from schema_migrations").fetchone()[0]
    finally:
        try:
            runs.release_run_locks(ctx)
        finally:
            conn.close()
    data = {"home": str(lay.root),
            "db": {"path": str(lay.db_path), "migrations_applied": applied, "schema_version": version},
            "python": sys.version.split()[0], "sqlite": caps, "browser": {"requested": False},
            "recovered_runs": recovered}
    if getattr(ns, "browser", False) or getattr(ns, "probe", False):
        from .bootstrap import with_context
        from . import browser as browser_svc
        def online(ctx):
            run_id = None
            if ns.browser:
                data.update(browser_svc.start_browser(ctx))
            if ns.probe:
                probe_data, run_id = browser_svc.probe(ctx)
                data.update(probe_data)
            return (data, run_id) if run_id else data
        return with_context(ns, warnings, online, write=True)
    return data

def register(sub, set_handler):
    p = sub.add_parser("init", help="检查本地依赖、建目录、迁移数据库、恢复前次中断的 run")
    p.add_argument("--browser", action="store_true", help="启动专用 Chrome（用户手动登录）")
    p.add_argument("--probe", action="store_true", help="受门禁的主动探测")
    set_handler(p, "init", run_local)
