# tests/integration/test_scan_cmd.py
import json
import pytest
from tests.conftest import load_fixture
from tests.helpers.fake_transport import FakeTransport
from tests.helpers.sleeper import Sleeper
from where_my_job.errors import Blocked, EnvError, Partial
from where_my_job.service import scan as scan_svc
from where_my_job.store import db, runs
from where_my_job.policy.ledger import Ledger

pytestmark = pytest.mark.usefixtures("online_adapter_enabled")

SENTINEL = "LEAK-SENTINEL https://www.zhipin.com/job_detail/SYN0101aaaa.html?securityId=LEAK SYN-LEAK-SENTINEL-PHONE"

@pytest.fixture
def fake(ctx, monkeypatch):
    box = {"made": 0}
    def install(script, **kw):
        t = FakeTransport(script, **kw)
        def make(c):
            box["made"] += 1
            return t
        sl = Sleeper(ctx.clock)
        monkeypatch.setattr(scan_svc, "make_transport", make)
        monkeypatch.setattr(scan_svc, "blank_check", lambda ctx: None)
        monkeypatch.setattr(scan_svc, "make_pacing", lambda c: (sl, lambda lo, hi: lo))
        box.update(t=t, sleep=sl)
        return t
    return install, box

def _strategy(tmp_path, pages=2, keywords=("AI产品经理",), cities=("合肥",)):
    s = {"schema_version": 1, "name": "测试", "budget": {"max_pages_per_run": pages * len(keywords) * len(cities),
                                                        "pause_between_actions_sec": [12, 22]},
         "searches": [{"keywords": list(keywords), "cities": list(cities), "pages": pages, "boss_filters": {}}]}
    p = tmp_path / f"s{pages}-{len(keywords)}.json"
    p.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    return str(p)

def _statuses(ctx, run_id):
    return [(r["task_key"].rsplit("|", 1)[-1] if "|" in r["task_key"] else r["task_key"], r["status"], r["failure_message"])
            for r in ctx.conn.execute("select task_key, status, failure_message from run_tasks where run_id=? order by rowid", (run_id,))]

def _ledger_n(ctx):
    return Ledger(ctx.conn, ctx.clock, ctx.home).actions_last_24h()

def test_two_pages_ok(ctx, fake, tmp_path):
    install, box = fake
    t = install([("joblist", load_fixture("api/page1_ok.json")), ("joblist", load_fixture("api/last_page_ok.json"))])
    data, run_id = scan_svc.run(ctx, _strategy(tmp_path))
    assert data["completed"] == 2 and data["saved_observations"] == 3 and data["saved_jobs"] == 3
    assert len(t.navigations) == 1 and t.scrolls == 1 and box["sleep"].calls == [12.0] and t.closed
    assert ctx.conn.execute("select status from runs where run_id=?", (run_id,)).fetchone()[0] == "ok"
    assert ctx.conn.execute("select count(distinct response_key) from run_tasks where run_id=?", (run_id,)).fetchone()[0] == 2
    assert ctx.conn.execute("select count(*) from sightings where raw_kind='api_entry'").fetchone()[0] == 3

def test_page2_code31_blocks_no_third_action(ctx, fake, tmp_path):
    install, _ = fake
    t = install([("joblist", load_fixture("api/page1_ok.json")), ("joblist", load_fixture("api/page2_code31.json")),
                 ("joblist", load_fixture("api/last_page_ok.json"))])
    with pytest.raises(Blocked) as ei:
        scan_svc.run(ctx, _strategy(tmp_path, pages=3))
    e = ei.value
    assert e.code == "RISK_DETECTED" and e.exit_code == 3 and e.run_id and e.data["saved_observations"] == 2
    assert len(t.navigations) + t.scrolls == 2 and len(t.script) == 1 and _ledger_n(ctx) == 2
    assert [s for _, s, _ in _statuses(ctx, e.run_id)] == ["ok", "blocked", "skipped"]
    assert _statuses(ctx, e.run_id)[2][2] == "stopped_after_failure"
    assert ctx.conn.execute("select status from runs where run_id=?", (e.run_id,)).fetchone()[0] == "blocked"
    assert Ledger(ctx.conn, ctx.clock, ctx.home).cooldown_until() is not None

def test_blocked_task_write_failure_still_persists_cooldown_and_exits_3(ctx, fake, tmp_path, monkeypatch):
    import sqlite3
    install, _ = fake
    install([("joblist", load_fixture("api/page1_ok.json")), ("joblist", load_fixture("api/page2_code31.json"))])
    real_finish_task = runs.finish_task
    def locked_on_blocked(conn, clock, task_id, **kw):
        if kw.get("status") == "blocked":
            raise sqlite3.OperationalError("database is locked")
        return real_finish_task(conn, clock, task_id, **kw)
    monkeypatch.setattr(runs, "finish_task", locked_on_blocked)
    with pytest.raises(Blocked) as ei:
        scan_svc.run(ctx, _strategy(tmp_path, pages=3))
    e = ei.value
    until = Ledger(ctx.conn, ctx.clock, ctx.home).cooldown_until()
    assert e.exit_code == 3 and e.code == "RISK_DETECTED" and until is not None
    assert e.retry["not_before"] == until
    assert "风控冷却已记录，但任务或 run 状态写入失败，已忽略" in ctx.warnings
    assert "database is locked" not in json.dumps([e.message, e.data, ctx.warnings], ensure_ascii=False)

def test_normal_empty_end_skips_rest_of_search(ctx, fake, tmp_path):
    install, _ = fake
    install([("joblist", load_fixture("api/empty_ok.json"))])
    data, run_id = scan_svc.run(ctx, _strategy(tmp_path, pages=3))
    assert data["empty_tasks"] == 1 and data["saved_observations"] == 0 and _ledger_n(ctx) == 1
    assert [(s, m) for _, s, m in _statuses(ctx, run_id)] == [("empty", None), ("skipped", "no_more_results"), ("skipped", "no_more_results")]

def test_has_more_unknown_stops_that_search(ctx, fake, tmp_path):
    install, _ = fake
    page = load_fixture("api/page1_ok.json"); page["zpData"]["hasMore"] = "maybe"
    install([("joblist", page)])
    data, run_id = scan_svc.run(ctx, _strategy(tmp_path, pages=2))
    assert data["completed"] == 1 and _statuses(ctx, run_id)[1][1:] == ("skipped", "has_more_unknown")

def test_first_group_ends_second_group_navigates(ctx, fake, tmp_path):
    install, _ = fake
    t = install([("joblist", load_fixture("api/last_page_ok.json")), ("joblist", load_fixture("api/page1_ok.json")),
                 ("joblist", load_fixture("api/last_page_ok.json"))])
    data, _ = scan_svc.run(ctx, _strategy(tmp_path, pages=2, keywords=("AI产品经理", "产品经理")))
    assert len(t.navigations) == 2 and t.scrolls == 1 and data["completed"] == 3

def test_unknown_after_saved_is_partial_exit_4_no_cooldown(ctx, fake, tmp_path):
    install, _ = fake
    install([("joblist", load_fixture("api/page1_ok.json")), ("joblist", load_fixture("api/unknown_code.json"))])
    with pytest.raises(Partial) as ei:
        scan_svc.run(ctx, _strategy(tmp_path, pages=3))
    assert ei.value.code == "PARTIAL_RESULT" and ei.value.exit_code == 4 and ei.value.run_id
    assert Ledger(ctx.conn, ctx.clock, ctx.home).cooldown_until() is None
    assert [s for _, s, _ in _statuses(ctx, ei.value.run_id)] == ["ok", "failed", "skipped"]

def test_capture_timeout_without_results_exit_2(ctx, fake, tmp_path):
    install, _ = fake
    t = install([])
    with pytest.raises(EnvError) as ei:
        scan_svc.run(ctx, _strategy(tmp_path, pages=1))
    assert ei.value.code == "CAPTURE_FAILED" and ei.value.exit_code == 2 and len(t.navigations) == 1

def test_unauthenticated_exit_2_no_cooldown(ctx, fake, tmp_path):
    install, _ = fake
    install([("joblist", load_fixture("api/unauthenticated.json"))])
    with pytest.raises(EnvError) as ei:
        scan_svc.run(ctx, _strategy(tmp_path, pages=1))
    assert ei.value.code == "UNAUTHENTICATED" and Ledger(ctx.conn, ctx.clock, ctx.home).cooldown_until() is None

def test_budget_rejected_before_run_and_transport(ctx, fake, tmp_path):
    install, box = fake
    install([("joblist", load_fixture("api/page1_ok.json"))])
    led = Ledger(ctx.conn, ctx.clock, ctx.home)
    with db.write_tx(ctx.conn):
        for _ in range(79):
            led.reserve("list_page", run_id="earlier")
    with pytest.raises(Blocked) as ei:
        scan_svc.run(ctx, _strategy(tmp_path, pages=2))
    assert ei.value.code == "BUDGET_EXHAUSTED" and ei.value.run_id is None
    assert box["made"] == 0 and ctx.conn.execute("select count(*) from runs where kind='scan'").fetchone()[0] == 0

def test_invalid_entry_keeps_valid_items_and_exits_4(ctx, fake, tmp_path):
    install, _ = fake
    page = load_fixture("api/last_page_ok.json")
    page["zpData"]["jobList"].append({"jobName": "no id"})
    install([("joblist", page)])
    with pytest.raises(Partial) as ei:
        scan_svc.run(ctx, _strategy(tmp_path, pages=1))
    assert ei.value.data["record_errors"] == 1 and ei.value.data["saved_observations"] == 1

def test_blocked_survives_close_failure_without_leak(ctx, fake, tmp_path):
    install, _ = fake
    install([("joblist", load_fixture("api/page2_code37.json"))], close_error=SENTINEL)
    with pytest.raises(Blocked) as ei:
        scan_svc.run(ctx, _strategy(tmp_path, pages=1))
    assert ei.value.exit_code == 3
    assert SENTINEL not in json.dumps([ctx.warnings, ei.value.data, ei.value.message], ensure_ascii=False)

def test_save_response_counts_observations_not_jobs(ctx):
    item = load_fixture("api/page1_ok.json")["zpData"]["jobList"][0]
    rid = runs.create_owned(ctx, kind="scan", config={}, planned=1)
    with db.write_tx(ctx.conn):
        tid = runs.add_planned_tasks(ctx.conn, ctx.clock, rid, [("k|p1", {"page": 1})])["k|p1"]
    first = scan_svc.save_response(ctx, rid, tid, page=1, request_id="req-1", items=[item, item])
    again = scan_svc.save_response(ctx, rid, tid, page=1, request_id="req-1", items=[item, item])
    assert (first.inserted, again.inserted, again.skipped_existing) == (2, 0, 2)
    assert ctx.conn.execute("select count(*) from sightings").fetchone()[0] == 2
    assert ctx.conn.execute("select count(*) from jobs").fetchone()[0] == 1
    assert [r[0] for r in ctx.conn.execute("select item_index from sightings order by item_index")] == [0, 1]
    q = json.loads(ctx.conn.execute("select query_json from run_tasks where task_id=?", (tid,)).fetchone()[0])
    assert q["response_key"] == first.response_key

def test_cli_scan_puts_run_id_top_level(cli, monkeypatch, tmp_path, clock):
    t = FakeTransport([("joblist", load_fixture("api/last_page_ok.json"))])
    monkeypatch.setattr(scan_svc, "make_transport", lambda c: t)
    monkeypatch.setattr(scan_svc, "blank_check", lambda ctx: None)
    monkeypatch.setattr(scan_svc, "make_pacing", lambda c: (Sleeper(clock), lambda lo, hi: lo))
    rc, env, _ = cli(["scan", "--strategy", _strategy(tmp_path, pages=1)])
    assert rc == 0 and env["run_id"].startswith("run_") and "SYN-SECURITY" not in json.dumps(env)

def test_partial_runs_what_fits_and_defers_the_rest(ctx, fake, tmp_path):
    """用户在 --dry-run 的 coverage 上确认过范围之后带 --partial：先跑当日额度内的，
    其余照样登记为任务再标 skipped，退出 4 并交代欠了多少——不是拒绝，也不是悄悄缩小范围。"""
    install, box = fake
    page = load_fixture("api/page1_ok.json")
    install([("joblist", page)] * 4)
    led = Ledger(ctx.conn, ctx.clock, ctx.home)
    with db.write_tx(ctx.conn):
        for _ in range(78):                                    # 只剩 2 次额度
            led.reserve("list_page", run_id="earlier")
    with pytest.raises(Partial) as ei:
        scan_svc.run(ctx, _strategy(tmp_path, pages=4), partial=True)
    data = ei.value.data
    assert data["planned"] == 4 and data["completed"] == 2     # planned 报的是用户要的全量
    assert data["deferred_actions"] == 2 and data["deferred_reason"] == "budget_24h"
    assert len(data["deferred_task_keys"]) == 2 and all("p" in k for k in data["deferred_task_keys"])
    statuses = _statuses(ctx, ei.value.run_id)
    assert [s for _, s, _ in statuses] == ["ok", "ok", "skipped", "skipped"]
    assert {m for _, s, m in statuses if s == "skipped"} == {"budget_24h_exhausted"}
    assert _ledger_n(ctx) == 80                                # 用满当日额度，一次都不超

def test_partial_is_a_no_op_when_the_plan_already_fits(ctx, fake, tmp_path):
    install, _ = fake
    install([("joblist", load_fixture("api/last_page_ok.json"))])
    data, run_id = scan_svc.run(ctx, _strategy(tmp_path, pages=1), partial=True)
    assert "deferred_actions" not in data and data["planned"] == 1 and data["completed"] == 1

def test_dry_run_reports_shortfall_instead_of_blocking(ctx, tmp_path, monkeypatch):
    """额度不够不是停止条件，是要如实报给用户的数字：dry-run 不联网、不写任何状态，
    退出 3 会被 agent 当成风控停手，于是它学会了只敢要一页。"""
    led = Ledger(ctx.conn, ctx.clock, ctx.home)
    with db.write_tx(ctx.conn):
        for _ in range(78):
            led.reserve("list_page", run_id="earlier")
    out = scan_svc.dry_run(ctx.home, ctx.clock, _strategy(tmp_path, pages=5))
    assert out["planned_actions"] == 5
    assert out["coverage"] == {"fits_budget": False, "planned_actions": 5, "remaining_24h": 2,
                               "tasks_today": 2, "tasks_deferred": 3}

def test_dry_run_still_blocks_on_cooldown(ctx, tmp_path):
    """额度放行，冷却不放行：退出 3 的语义留给真正该停手的事。"""
    from where_my_job.policy.gate import Gate
    gate = Gate(ctx)
    with db.write_tx(ctx.conn):
        gate.ledger.set_cooldown("risk_detected")
    with pytest.raises(Blocked) as ei:
        scan_svc.dry_run(ctx.home, ctx.clock, _strategy(tmp_path, pages=1))
    assert ei.value.code == "COOLDOWN_ACTIVE"
