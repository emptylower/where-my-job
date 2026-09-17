# tests/security/test_risk_matrix.py
"""设计 v3 §13「风控离线」「预算/计划」与第 1 轮评审 P39 替换表逐项对照。"""
import json, os, subprocess, sys, textwrap
from datetime import timedelta
from pathlib import Path
import pytest
from tests.conftest import FIXTURES, load_fixture
from tests.helpers.fake_transport import FakeTransport
from tests.helpers.sleeper import Sleeper, rewind_wall
from where_my_job.clock import parse_iso
from where_my_job.errors import Blocked, EnvError, Partial
from where_my_job.launcher.chrome import BrowserState, VerifiedBrowser
from where_my_job.policy.ledger import Ledger
from where_my_job.service import scan as scan_svc, deepdive_online, browser as browser_svc
from where_my_job.store import db

pytestmark = pytest.mark.usefixtures("online_adapter_enabled")

VB = VerifiedBrowser(BrowserState(pid=4242, create_time=1000.0, exe="/x", profile="/p", port=9222, started_at="t"),
                     "ws://127.0.0.1:9222/devtools/browser/abc")
SENTINEL = "LEAK-SENTINEL https://www.zhipin.com/job_detail/SYN0101aaaa.html?securityId=LEAK SYN-LEAK-SENTINEL-PHONE"

class OkLauncher:
    def verify(self): return VB
    def blank_check(self, verified, allow_target_id=None): return None
    def stop(self): return {"stopped": True, "pid": 4242}

@pytest.fixture
def net(ctx, monkeypatch):
    state = {"transports": [], "made": 0}
    def make(*args):
        state["made"] += 1
        return state["transports"].pop(0)
    sleeper = Sleeper(ctx.clock)
    for mod in (scan_svc, deepdive_online, browser_svc):
        monkeypatch.setattr(mod, "make_transport", make)
        monkeypatch.setattr(mod, "make_pacing", lambda c: (sleeper, lambda lo, hi: lo))
    monkeypatch.setattr(scan_svc, "blank_check", lambda ctx: None)
    monkeypatch.setattr(deepdive_online, "make_launcher", lambda lay: OkLauncher())
    monkeypatch.setattr(browser_svc, "make_launcher", lambda lay: OkLauncher())
    def queue(*scripts, close_error=None):
        ts = [FakeTransport(list(s), close_error=close_error) for s in scripts]
        state["transports"].extend(ts)
        return ts
    state.update(queue=queue, sleep=sleeper)
    return state

def _strategy(tmp_path, pages=3, name="s", pause=(12, 22)):
    s = {"schema_version": 1, "name": name, "budget": {"max_pages_per_run": pages, "pause_between_actions_sec": list(pause)},
         "searches": [{"keywords": ["AI产品经理"], "cities": ["合肥"], "pages": pages, "boss_filters": {}}]}
    p = tmp_path / f"{name}-{pages}.json"
    p.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    return str(p)

def _ledger(ctx):
    return Ledger(ctx.conn, ctx.clock, ctx.home)

def _tasks(ctx, run_id):
    return [(r["status"], r["failure_message"]) for r in
            ctx.conn.execute("select status, failure_message from run_tasks where run_id=? order by rowid", (run_id,))]

def _run_status(ctx, run_id):
    return ctx.conn.execute("select status from runs where run_id=?", (run_id,)).fetchone()[0]

P1 = lambda: ("joblist", load_fixture("api/page1_ok.json"))
SECURITY_DOC = "https://www.zhipin.com/web/common/security-check.html"

# ---- 第一页正常，第二页 31 / 37 / 验证码 ----
@pytest.mark.parametrize("second", ["api/page2_code31.json", "api/page2_code37.json", "api/captcha_html.json"])
def test_page2_risk_stops_after_two_actions(ctx, net, tmp_path, second):
    (t,) = net["queue"]([P1(), ("joblist", load_fixture(second)), ("joblist", load_fixture("api/last_page_ok.json"))])
    trigger = ctx.clock.now()
    with pytest.raises(Blocked) as ei:
        scan_svc.run(ctx, _strategy(tmp_path))
    e = ei.value
    assert e.exit_code == 3 and e.code == "RISK_DETECTED"
    assert len(t.navigations) + t.scrolls == 2 and len(t.script) == 1 and net["made"] == 1 and t.closed
    assert len(_ledger(ctx).view().entries) == 2
    assert parse_iso(_ledger(ctx).cooldown_until()) >= trigger + timedelta(hours=4)
    assert ctx.conn.execute("select count(*) from sightings").fetchone()[0] == 2
    assert _tasks(ctx, e.run_id) == [("ok", None), ("blocked", e.data["reason"]), ("skipped", "stopped_after_failure")]
    assert _run_status(ctx, e.run_id) == "blocked"

# ---- 第一页已保存，第二页 body 缺失 / 超时 / 非 JSON / 未知码 ----
@pytest.mark.parametrize("second", [("joblist", None), ("timeout",), ("joblist", {"__not_json__": True, "body": "<html>oops</html>"}),
                                    ("joblist", load_fixture("api/unknown_code.json"))])
def test_page2_unknown_after_saved_exit_4(ctx, net, tmp_path, second):
    (t,) = net["queue"]([P1(), second, ("joblist", load_fixture("api/last_page_ok.json"))])
    with pytest.raises(Partial) as ei:
        scan_svc.run(ctx, _strategy(tmp_path))
    assert ei.value.exit_code == 4 and len(t.navigations) + t.scrolls == 2 and _ledger(ctx).cooldown_until() is None
    assert [s for s, _ in _tasks(ctx, ei.value.run_id)] == ["ok", "failed", "skipped"]
    assert _run_status(ctx, ei.value.run_id) == "partial"

def test_first_page_unknown_without_results_exit_2(ctx, net, tmp_path):
    (t,) = net["queue"]([("joblist", load_fixture("api/unknown_code.json"))])
    with pytest.raises(EnvError) as ei:
        scan_svc.run(ctx, _strategy(tmp_path))
    assert ei.value.code == "CAPTURE_FAILED" and len(_ledger(ctx).view().entries) == 1 and _run_status(ctx, ei.value.run_id) == "failed"

def test_normal_empty_end_skips_rest(ctx, net, tmp_path):
    net["queue"]([("joblist", load_fixture("api/empty_ok.json"))])
    data, run_id = scan_svc.run(ctx, _strategy(tmp_path))
    assert _tasks(ctx, run_id) == [("empty", None), ("skipped", "no_more_results"), ("skipped", "no_more_results")]
    assert _ledger(ctx).cooldown_until() is None

@pytest.mark.parametrize("fx", ["api/empty_has_more_missing.json", "api/empty_has_more_string.json", "api/empty_has_more_true.json"])
def test_empty_without_end_marker_is_unknown(ctx, net, tmp_path, fx):
    net["queue"]([("joblist", load_fixture(fx))])
    with pytest.raises(EnvError) as ei:
        scan_svc.run(ctx, _strategy(tmp_path))
    assert ei.value.code == "CAPTURE_FAILED"

def test_wrong_metadata_not_stored_and_own_risk_response_wins(ctx, net, tmp_path):
    net["queue"]([("joblist", load_fixture("api/page1_ok.json"), {"query": {"page": "9"}}),
                  ("foreign", load_fixture("api/page1_ok.json")),
                  ("joblist", load_fixture("api/page2_code37.json"), {"query": {"page": "9"}})])
    with pytest.raises(Blocked):
        scan_svc.run(ctx, _strategy(tmp_path))
    assert ctx.conn.execute("select count(*) from sightings").fetchone()[0] == 0

# ---- 详情/公司：同站风险正文、跨域与错误岗位重定向 ----
@pytest.fixture
def seeded(cli):
    cli(["import", str(FIXTURES / "legacy" / "合肥_AI产品经理.json")])

def test_detail_risk_page_stops_before_company(ctx, net, seeded):
    (t,) = net["queue"]([("page", load_fixture("pages/job_detail_risk.json")), ("page", load_fixture("pages/company_ok.json"))])
    r = deepdive_online.acquire(ctx, "boss:SYN0001aaaa", skip_company=False)
    assert isinstance(r.blocked, Blocked) and len(t.navigations) == 1 and len(t.script) == 1
    assert ctx.conn.execute("select count(*) from evidence").fetchone()[0] == 0 and t.closed

@pytest.mark.parametrize("target,attr", [("https://evil.example/x", "failure"),
                                         ("https://www.zhipin.com/web/common/security-check.html", "blocked")])
def test_detail_redirects_never_send_target_document(ctx, net, seeded, target, attr):
    (t,) = net["queue"]([("redirect", target), ("page", load_fixture("pages/job_detail_ok.json"))])
    r = deepdive_online.acquire(ctx, "boss:SYN0001aaaa", skip_company=True)
    assert getattr(r, attr) is not None and target not in t.documents_sent and t.evaluations == 0

# ---- 冷却中各在线入口在传输创建前拒绝；缓存/状态/停止仍可用 ----
def test_cooldown_refuses_all_online_entries_before_transport(cli, ctx, net, seeded, tmp_path):
    net["queue"]([P1()], [("page", load_fixture("pages/job_detail_ok.json"))], [P1()])
    with db.write_tx(ctx.conn):
        _ledger(ctx).set_cooldown("risk_response", platform_code=37)
    for call in (lambda: scan_svc.run(ctx, _strategy(tmp_path)),
                 lambda: deepdive_online.acquire(ctx, "boss:SYN0001aaaa", skip_company=True),
                 lambda: browser_svc.probe(ctx)):
        with pytest.raises(Blocked) as ei:
            call()
        assert ei.value.code == "COOLDOWN_ACTIVE" and ei.value.run_id is None
    assert net["made"] == 0 and ctx.conn.execute("select count(*) from runs where kind in ('scan','deepdive')").fetchone()[0] == 0
    assert cli(["status"])[0] == 0
    assert cli(["browser", "stop"])[0] == 0
    assert cli(["deepdive", "boss:SYN0001aaaa", "--cached"])[0] != 3

# ---- 第 80 / 81 次；两个进程与 home 别名 ----
_RESERVE = textwrap.dedent("""
    import sys, pathlib
    from where_my_job.paths import Layout
    from where_my_job.clock import SystemClock
    from where_my_job.store import db
    from where_my_job.policy.ledger import Ledger
    from where_my_job.errors import Blocked
    lay = Layout(pathlib.Path(sys.argv[1])); clock = SystemClock()
    conn = db.open_db(lay.db_path, clock=clock)
    led = Ledger(conn, clock, lay); ok = 0
    for _ in range(int(sys.argv[2])):
        try:
            with db.write_tx(conn):
                led.reserve("list_page", run_id="proc")
            ok += 1
        except Blocked:
            pass
    print(ok)
""")

def test_two_processes_through_home_alias_share_80(ctx, tmp_path):
    alias = tmp_path / "alias"; os.symlink(ctx.home.root, alias)
    procs = [subprocess.Popen([sys.executable, "-c", _RESERVE, str(home), "45"], stdout=subprocess.PIPE, text=True)
             for home in (ctx.home.root, alias)]
    total = sum(int(p.communicate(timeout=120)[0].strip()) for p in procs)
    extra = subprocess.run([sys.executable, "-c", _RESERVE, str(alias), "1"], capture_output=True, text=True, timeout=60)
    assert total == 80 and extra.stdout.strip() == "0"
    assert len(_ledger(ctx).view().entries) == 80

_RESERVE_ENV = textwrap.dedent("""
    import sys
    from where_my_job.paths import ensure_layout
    from where_my_job.clock import SystemClock
    from where_my_job.store import db
    from where_my_job.policy.ledger import Ledger
    from where_my_job.errors import Blocked
    lay = ensure_layout(); clock = SystemClock()
    conn = db.open_db(lay.db_path, clock=clock)
    led = Ledger(conn, clock, lay); ok = 0
    for _ in range(int(sys.argv[1])):
        try:
            with db.write_tx(conn):
                led.reserve("list_page", run_id="proc")
            ok += 1
        except Blocked:
            pass
    print(ok)
""")

def test_quota_cannot_be_reset_by_changing_cwd(ctx, tmp_path):
    env = dict(os.environ, WMJ_HOME=str(ctx.home.root))
    cwds = [tmp_path / "cwd-a", tmp_path / "cwd-b"]
    for d in cwds:
        d.mkdir()
    procs = [subprocess.Popen([sys.executable, "-c", _RESERVE_ENV, "45"], stdout=subprocess.PIPE, text=True,
                              cwd=str(d), env=env) for d in cwds]
    total = sum(int(p.communicate(timeout=120)[0].strip()) for p in procs)
    extra = subprocess.run([sys.executable, "-c", _RESERVE_ENV, "1"], capture_output=True, text=True, timeout=60,
                           cwd=str(cwds[1]), env=env)
    assert total == 80 and extra.stdout.strip() == "0"
    assert len(_ledger(ctx).view().entries) == 80

def test_second_home_sharing_only_profile_is_refused(ctx, net, tmp_path, monkeypatch, capsys):
    from where_my_job.cli import main as cli_main
    home2 = tmp_path / "home2"; home2.mkdir()
    ctx.home.browser_profile.mkdir(exist_ok=True)
    os.symlink(ctx.home.browser_profile, home2 / "browser-profile")
    net["queue"]([P1()])
    before = len(_ledger(ctx).view().entries)
    monkeypatch.setenv("WMJ_HOME", str(home2))
    rc = cli_main.main(["scan", "--strategy", _strategy(tmp_path, pages=1)])
    env = json.loads(capsys.readouterr().out)
    assert rc == 2 and env["errors"][0]["code"] == "PROFILE_NOT_OWNED" and net["made"] == 0
    db2 = home2 / "state" / "where-my-job.sqlite3"
    if db2.exists():
        c2 = db.open_db(db2)
        assert c2.execute("select count(*) from runs").fetchone()[0] == 0
        assert c2.execute("select count(*) from network_policy_state").fetchone()[0] == 0
        c2.close()
    assert len(_ledger(ctx).view().entries) == before

# ---- 新 run 较慢策略与墙钟回拨 ----
def test_slower_strategy_waits_and_rollback_after_cooldown_blocks(ctx, net, tmp_path):
    net["queue"]([("joblist", load_fixture("api/last_page_ok.json"))], [("joblist", load_fixture("api/last_page_ok.json"))])
    scan_svc.run(ctx, _strategy(tmp_path, pages=1, name="fast"))
    ctx.clock.advance(5)
    net["sleep"].calls.clear()
    scan_svc.run(ctx, _strategy(tmp_path, pages=1, name="slow", pause=(30, 40)))
    assert net["sleep"].calls == [25.0]
    with db.write_tx(ctx.conn):
        _ledger(ctx).set_cooldown("risk_page")
    until, used = _ledger(ctx).cooldown_until(), len(_ledger(ctx).view().entries)
    rewind_wall(ctx.clock, 7200)
    with pytest.raises(Blocked) as ei:
        scan_svc.run(ctx, _strategy(tmp_path, pages=1, name="after"))
    assert ei.value.code == "CLOCK_ANOMALY" and _ledger(ctx).cooldown_until() == until and len(_ledger(ctx).view().entries) == used

# ---- 风控后清理失败 ----
def test_blocked_then_close_failure_keeps_exit_3_and_no_leak(ctx, net, tmp_path):
    net["queue"]([P1(), ("joblist", load_fixture("api/sentinel_message.json"))], close_error=SENTINEL)
    with pytest.raises(Blocked) as ei:
        scan_svc.run(ctx, _strategy(tmp_path))
    run_row = ctx.conn.execute("select status, summary_json from runs where run_id=?", (ei.value.run_id,)).fetchone()
    tasks = json.dumps([dict(r) for r in ctx.conn.execute("select * from run_tasks")], ensure_ascii=False)
    public = json.dumps([ei.value.message, ei.value.data, ctx.warnings, run_row["summary_json"], tasks], ensure_ascii=False)
    assert run_row["status"] == "blocked" and ctx.conn.execute("select count(*) from sightings").fetchone()[0] == 2
    assert "LEAK" not in public and "SYN-LEAK-SENTINEL-PHONE" not in public and _ledger(ctx).cooldown_until()

# ---- 详情两次 evaluate + 公司两次 evaluate，经真实 04 入口组包 ----
def test_four_reads_two_snapshots_through_04_deepdive(cli, ctx, net, seeded):
    (t,) = net["queue"]([("page", load_fixture("pages/job_detail_ok.json")), ("page", load_fixture("pages/company_ok.json"))])
    rc, env, _ = cli(["deepdive", "boss:SYN0001aaaa"])
    assert rc == 0 and t.evaluations == 4 and "bundle_id" in json.dumps(env["data"])
    kinds = [r[0] for r in ctx.conn.execute("select kind from evidence order by rowid")]
    assert kinds == ["job_detail_page", "company_page"]

# ---- probe 失败与普通环境失败：顶层 run_id、全部 run 终结、probe 不计入扫描覆盖 ----
def test_probe_and_env_failures_are_traceable_and_terminal(cli, ctx, net, tmp_path):
    net["queue"]([("joblist", load_fixture("api/unauthenticated.json"))], [("timeout",)])
    rc, env, _ = cli(["init", "--probe"])
    assert rc == 2 and env["run_id"] and env["errors"][0]["code"] == "UNAUTHENTICATED"
    with pytest.raises(EnvError) as ei:
        scan_svc.run(ctx, _strategy(tmp_path, pages=1))
    assert ei.value.run_id
    assert ctx.conn.execute("select count(*) from runs where status='running'").fetchone()[0] == 0
    rc, env, _ = cli(["status"])
    assert env["data"]["runs"]["last_probe"]["status"] == "failed" and env["data"]["runs"]["last_scan"]["status"] == "failed"

# ---- 采集或读取期间出现的风控主文档（Document 拦截记录必须被读取，不得降级为超时）----
def test_security_document_during_list_capture_blocks_with_cooldown(ctx, net, tmp_path):
    (t,) = net["queue"]([("doc_during_capture", SECURITY_DOC), P1(), ("joblist", load_fixture("api/last_page_ok.json"))])
    trigger = ctx.clock.now()
    with pytest.raises(Blocked) as ei:
        scan_svc.run(ctx, _strategy(tmp_path))
    e = ei.value
    assert e.exit_code == 3 and e.code == "RISK_DETECTED"
    # 拦截只覆盖本工具自己的导航：提交之后页面跳到验证页会被加载，但绝不被使用——退出 3、冷却、不入库一条不少
    assert len(t.navigations) == 1 and t.scrolls == 0 and len(t.script) == 2
    assert e.data["reason"] == "risk_page"
    assert parse_iso(_ledger(ctx).cooldown_until()) >= trigger + timedelta(hours=4)
    assert len(_ledger(ctx).view().entries) == 1 and ctx.conn.execute("select count(*) from sightings").fetchone()[0] == 0
    assert _tasks(ctx, e.run_id) == [("blocked", e.data["reason"]), ("skipped", "stopped_after_failure"),
                                     ("skipped", "stopped_after_failure")]
    assert _run_status(ctx, e.run_id) == "blocked" and t.closed

def test_security_document_during_detail_read_blocks_before_company(ctx, net, seeded):
    (t,) = net["queue"]([("page", load_fixture("pages/job_detail_ok.json")), ("doc_during_evaluate", SECURITY_DOC),
                         ("page", load_fixture("pages/company_ok.json"))])
    trigger = ctx.clock.now()
    r = deepdive_online.acquire(ctx, "boss:SYN0001aaaa", skip_company=False)
    assert isinstance(r.blocked, Blocked) and r.blocked.exit_code == 3 and r.failure is None
    assert len(t.navigations) == 1 and t.evaluations == 1 and len(t.script) == 1 and SECURITY_DOC not in t.documents_sent
    assert parse_iso(_ledger(ctx).cooldown_until()) >= trigger + timedelta(hours=4)
    assert ctx.conn.execute("select count(*) from evidence").fetchone()[0] == 0 and t.closed

# ---- 对照表：每个条目至少有一个存在的测试 ----
COVERAGE = {
    "第一页成功/第二页31/37/验证码": "tests/security/test_risk_matrix.py::test_page2_risk_stops_after_two_actions",
    "第二页空body/超时/非JSON/未知码": "tests/security/test_risk_matrix.py::test_page2_unknown_after_saved_exit_4",
    "首页未知且无结果": "tests/security/test_risk_matrix.py::test_first_page_unknown_without_results_exit_2",
    "正常空结果": "tests/security/test_risk_matrix.py::test_normal_empty_end_skips_rest",
    "空列表缺终页标记": "tests/security/test_risk_matrix.py::test_empty_without_end_marker_is_unknown",
    "响应归属与风险优先": "tests/security/test_risk_matrix.py::test_wrong_metadata_not_stored_and_own_risk_response_wins",
    "详情/公司风险正文": "tests/security/test_risk_matrix.py::test_detail_risk_page_stops_before_company",
    "跨域与错误岗位重定向": "tests/security/test_risk_matrix.py::test_detail_redirects_never_send_target_document",
    "公司页限制": "tests/integration/test_acquire.py::test_company_risk_page_keeps_detail_sets_blocked_and_stores_no_risk_text",
    "冷却中各入口": "tests/security/test_risk_matrix.py::test_cooldown_refuses_all_online_entries_before_transport",
    "80/81与两进程别名": "tests/security/test_risk_matrix.py::test_two_processes_through_home_alias_share_80",
    "跨home共享profile": "tests/security/test_risk_matrix.py::test_second_home_sharing_only_profile_is_refused",
    "较慢策略与时间回拨": "tests/security/test_risk_matrix.py::test_slower_strategy_waits_and_rollback_after_cooldown_blocks",
    "dry-run零副作用": "tests/integration/test_scan_dry_run.py::test_dry_run_has_zero_side_effects_after_init",
    "风控后清理失败": "tests/security/test_risk_matrix.py::test_blocked_then_close_failure_keeps_exit_3_and_no_leak",
    "两页四次读取经04组包": "tests/security/test_risk_matrix.py::test_four_reads_two_snapshots_through_04_deepdive",
    "probe与环境失败可追溯": "tests/security/test_risk_matrix.py::test_probe_and_env_failures_are_traceable_and_terminal",
    "84页计划": "tests/unit/service/test_scan_plan_contract.py::test_80_allowed_84_rejected_by_the_same_expander",
    "锁占用": "tests/unit/policy/test_layout_lock.py::test_second_process_through_home_alias_gets_resource_busy",
    "非回环监听": "tests/unit/launcher/test_chrome.py::test_verify_rejections",
    "Document拦截只放行不修改": "tests/unit/adapter/test_cdp.py::test_document_interception_continue_unmodified_or_fail_blocked_by_client",
    "公开错误无泄露": "tests/unit/service/test_network_run.py::test_unexpected_exception_is_internal_without_text",
    "列表采集期间风控主文档": "tests/security/test_risk_matrix.py::test_security_document_during_list_capture_blocks_with_cooldown",
    "详情读取期间风控主文档": "tests/security/test_risk_matrix.py::test_security_document_during_detail_read_blocks_before_company",
    "风控后任务写入失败仍持久冷却": "tests/integration/test_scan_cmd.py::test_blocked_task_write_failure_still_persists_cooldown_and_exits_3",
    "配额不能换cwd重置": "tests/security/test_risk_matrix.py::test_quota_cannot_be_reset_by_changing_cwd",
    "矩阵重复去重": "tests/unit/normalize/test_strategy_plan.py::test_multi_value_filters_expand_combinations_and_dedupe_duplicates",
    "dry-run活动WAL写者不新增文件": "tests/integration/test_scan_dry_run.py::test_dry_run_with_live_wal_writer_creates_no_new_files",
    "dry-run孤立WAL拒绝且不建shm": "tests/integration/test_scan_dry_run.py::test_dry_run_refuses_orphan_wal_without_creating_shm",
}

def test_coverage_table_points_to_existing_tests():
    import re
    root = Path(__file__).resolve().parents[2]
    for item, ref in COVERAGE.items():
        path, name = ref.split("::")
        src = (root / path).read_text(encoding="utf-8")
        assert re.search(rf"^def {re.escape(name)}\(", src, re.M), f"{item} → {ref} 不存在"

def test_detail_redirect_to_another_job_page_is_followed_but_fails_on_the_landing_check(ctx, net, seeded):
    """同站主文档在导航期间被放行（平台会插自己的跳转），但落点不是本次要读的岗位页就终止，且不读取页面。"""
    other = "https://www.zhipin.com/job_detail/SYN9999zzzz.html"
    (t,) = net["queue"]([("redirect", other), ("page", load_fixture("pages/job_detail_ok.json"))])
    r = deepdive_online.acquire(ctx, "boss:SYN0001aaaa", skip_company=True)
    assert r.failure is not None and other in t.documents_sent and t.evaluations == 0
    assert ctx.conn.execute("select count(*) from evidence").fetchone()[0] == 0
