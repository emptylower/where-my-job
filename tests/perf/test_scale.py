# tests/perf/test_scale.py
import json, multiprocessing as mp, os, platform, queue, shutil, sqlite3, subprocess, sys, time
from datetime import timedelta
import pytest
from tests.conftest import FIXTURES
from where_my_job.normalize.legacy import map_legacy_record
from where_my_job.store import db, runs, jobs, sightings, attrs

pytestmark = pytest.mark.perf

def _seed(conn, clock, n_jobs=5000, attrs_per_job=60):
    base = json.loads((FIXTURES / "legacy" / "合肥_AI产品经理.json").read_text(encoding="utf-8"))["jobs"][0]
    now = clock.now()
    with db.write_tx(conn):
        run_id = runs.create(conn, clock, kind="import", config={}, planned=1)
        task_id = runs.add_task(conn, clock, run_id, task_key="perf", query={})
        for i in range(n_jobs):
            rec = dict(base, encrypt_job_id=f"SYNPERF{i:06d}", job_link=f"https://www.zhipin.com/job_detail/SYNPERF{i:06d}.html",
                       title=("AI产品经理" if i % 3 else "AI 全栈工程师"), job_id=f"{i:016d}",
                       security_id=f"SYN-SECURITY-{i}", lid=f"SYN.lid.{i}")
            m = map_legacy_record(rec)
            jobs.ensure(conn, clock, m.job_id, "boss", m.source_job_id, m.legacy_job_id, None)
            for sha, age_days in (("p" * 64, 0), ("b" * 64, 7), ("c" * 64, 30)):
                sightings.insert(conn, clock, job_id=m.job_id, run_id=run_id, task_id=task_id, file_sha256=sha, item_index=i,
                                 page=None, observed_at=now - timedelta(days=age_days), observed_at_raw=None,
                                 time_precision="file_snapshot", tz_assumption=None, raw_kind="legacy_mapped",
                                 raw=m.raw_private, fact=m.fact)
            jobs.refresh_current(conn, clock, m.job_id)
            for k in range(attrs_per_job):
                attrs.set_attr(conn, clock, m.job_id, f"custom.k{k}", k, source="agent")
        runs.finish(conn, clock, run_id, status="ok", completed=1, summary={})

def _status_loop(home, ready, stop, failures):
    env = dict(os.environ, WMJ_HOME=home)
    first = True
    while not stop.is_set():
        r = subprocess.run([sys.executable, "-m", "where_my_job", "status"], env=env, capture_output=True, text=True)
        try:
            ok = r.returncode == 0 and json.loads(r.stdout)["command"] == "status"
        except (ValueError, KeyError):
            ok = False
        if not ok:
            failures.put((r.returncode, r.stdout[-2000:], r.stderr[-2000:]))
        if first:
            ready.set()
            first = False

def test_scale_match_panel_query_with_concurrent_status(cli, wmj_home, clock):
    conn = db.open_db(wmj_home.db_path, clock=clock); db.migrate(conn, wmj_home)
    _seed(conn, clock)
    with db.write_tx(conn):
        running_id = runs.create(conn, clock, kind="scan", config={"perf": True}, planned=1)   # 模拟进行中的 run
    counts = tuple(conn.execute(f"select count(*) from {t}").fetchone()[0] for t in ("jobs", "sightings", "job_attrs"))
    j0 = conn.execute("select first_seen_at, last_seen_at, hit_count from jobs where job_id='boss:SYNPERF000000'").fetchone()
    conn.close()
    assert counts == (5000, 15000, 300000)
    assert j0["hit_count"] == 3 and j0["first_seen_at"] < j0["last_seen_at"]
    shutil.copy(FIXTURES / "scoring.minimal.json", wmj_home.config("scoring.json"))
    shutil.copy(FIXTURES / "profile.synthetic.json", wmj_home.config("profile.json"))

    context = mp.get_context("spawn")
    ready, stop, failures = context.Event(), context.Event(), context.Queue()
    reader = context.Process(target=_status_loop, args=(str(wmj_home.root), ready, stop, failures), daemon=True)
    reader.start()
    try:
        assert ready.wait(60), "并发 status 进程未就绪"
        t0 = time.perf_counter(); rc, env, _ = cli(["match"]); t_match = time.perf_counter() - t0
        assert rc == 0 and env["data"]["jobs_evaluated"] == 5000, env
        t0 = time.perf_counter(); rc, env, _ = cli(["panel"]); t_panel = time.perf_counter() - t0
        assert rc == 0, env
        panel_rows, panel_total, panel_truncated = env["data"]["rows"], env["data"]["total"], env["data"]["truncated"]
        t0 = time.perf_counter(); rc, env, _ = cli(["job", "list", "--filter", "score>=60", "--page-size", "500"])
        t_query = time.perf_counter() - t0
        assert rc == 0, env
    finally:
        stop.set()
        reader.join(30)
        if reader.is_alive():
            reader.kill()
    errors = []
    while True:
        try:
            errors.append(failures.get(timeout=0.2))
        except queue.Empty:
            break
    assert errors == [], errors[:3]
    c = db.open_db(wmj_home.db_path)
    try:
        assert c.execute("select status from runs where run_id=?", (running_id,)).fetchone()[0] == "running"
    finally:
        c.close()
    print(f"\npython={platform.python_version()} sqlite={sqlite3.sqlite_version} machine={platform.machine()} os={platform.platform()}")
    print(f"match={t_match:.2f}s panel={t_panel:.2f}s query(score>=60)={t_query:.2f}s "
          f"panel_main_rows={panel_rows}/{panel_total} truncated={panel_truncated}")
    assert panel_rows == 500 and panel_truncated is True       # 面板计时对应 500 行渲染，不冒充 5000 行全量
    assert t_match < 2.0, f"match {t_match:.2f}s"
    assert t_panel < 3.0, f"panel {t_panel:.2f}s（渲染 {panel_rows}/{panel_total} 行）"
