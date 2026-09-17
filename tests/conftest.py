from __future__ import annotations
import io, json, pathlib
from datetime import datetime, timezone
import pytest
from where_my_job.clock import FixedClock

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "synthetic"

@pytest.fixture
def wmj_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WMJ_HOME", str(tmp_path / "wmj-home"))
    from where_my_job import paths
    return paths.ensure_layout()

@pytest.fixture
def clock():
    return FixedClock(datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc))

@pytest.fixture
def conn(wmj_home, clock):
    from where_my_job.store import db
    c = db.open_db(wmj_home.db_path, clock=clock)
    db.migrate(c, wmj_home, clock=clock)
    yield c
    c.close()

@pytest.fixture
def ctx(wmj_home, clock, conn):
    from where_my_job.service.context import Context
    c = Context(home=wmj_home, clock=clock, conn=conn, warnings=[], run_locks={}, stderr=io.StringIO())
    yield c
    for handle in c.run_locks.values():
        handle.close()

@pytest.fixture
def cli(wmj_home, clock, monkeypatch, capsys):
    """运行 CLI，返回 (exit_code, envelope, stderr)。时钟固定。"""
    from where_my_job.cli import main as cli_main
    monkeypatch.setattr(cli_main, "make_clock", lambda: clock)
    def run(argv: list[str]):
        rc = cli_main.main(argv)
        cap = capsys.readouterr()
        return rc, json.loads(cap.out), cap.err
    return run

def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

@pytest.fixture
def online_adapter_enabled(monkeypatch):
    from where_my_job import release
    monkeypatch.setattr(release, "ONLINE_ADAPTER_DEFAULT", "enabled")
