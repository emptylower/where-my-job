# tests/integration/test_scan_dry_run.py
import hashlib, json
from pathlib import Path
from tests.conftest import FIXTURES
from tests.helpers.sleeper import rewind_wall
from where_my_job.config import search_codes
from where_my_job.store import db
from where_my_job.policy.ledger import Ledger

S = FIXTURES / "strategies"

def _tree(root: Path):
    if not root.exists():
        return None
    return sorted((str(p.relative_to(root)), p.is_dir(), None if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
                  for p in root.rglob("*"))

def test_dry_run_reports_plan_budget_and_labels(cli):
    rc, env, _ = cli(["scan", "--strategy", str(S / "scan_salary_405.json"), "--dry-run"])
    assert rc == 0, env
    d = env["data"]
    assert d["dry_run"] is True and d["planned_actions"] == 2 and len(d["tasks"]) == 2
    # 计划原文写 compile_filter(...).label（ASCII "10-20K"），但 02 已定案 filter_labels 用 display_label
    # （en dash "10–20K"，见 strategy_plan 注释与 test_search_codes）；此处按 02 语义修正期望值。
    assert {t["filter_labels"]["salary"] for t in d["tasks"]} == {
        search_codes.display_label("salary", search_codes.compile_filter("salary", "405").code),
        search_codes.display_label("salary", search_codes.compile_filter("salary", "20-50K").code)}
    assert d["budget"] == {"remaining_24h": 80, "budget_24h": 80, "cooldown_until": None}
    assert env["run_id"] is None

def _wal_files(tree):
    return sorted(name for name, _, _ in tree if name.endswith(("-wal", "-shm")))

def test_dry_run_has_zero_side_effects_after_init(cli, wmj_home):
    rc, _, _ = cli(["init"])
    assert rc == 0
    before = _tree(wmj_home.root)
    rc, env, _ = cli(["scan", "--strategy", str(S / "scan_first_page.json"), "--dry-run"])
    assert rc == 0, env
    after = _tree(wmj_home.root)
    assert _wal_files(after) == _wal_files(before) == []      # 只读打开不得生成 -shm / -wal
    assert after == before                                     # 名称、类型、内容哈希全部不变

def test_dry_run_with_live_wal_writer_creates_no_new_files(cli, wmj_home):
    rc, _, _ = cli(["init"])
    assert rc == 0
    writer = db.open_db(wmj_home.db_path)
    try:
        with db.write_tx(writer):
            writer.execute("insert into network_policy_state(browser_profile_id, updated_at) "
                           "values ('syn-other-profile', '2026-09-14T00:00:00.000000Z')")
        names_before = {name for name, _, _ in _tree(wmj_home.root)}
        assert any(n.endswith("-wal") for n in names_before) and any(n.endswith("-shm") for n in names_before)
        rc, env, _ = cli(["scan", "--strategy", str(S / "scan_first_page.json"), "--dry-run"])
        assert rc == 0, env
        assert {name for name, _, _ in _tree(wmj_home.root)} == names_before   # 只读取既有附属文件，不新增文件
    finally:
        writer.close()

def test_dry_run_refuses_orphan_wal_without_creating_shm(cli, wmj_home):
    rc, _, _ = cli(["init"])
    assert rc == 0
    orphan = wmj_home.db_path.with_name(wmj_home.db_path.name + "-wal")
    orphan.write_bytes(b"")
    before = _tree(wmj_home.root)
    rc, env, _ = cli(["scan", "--strategy", str(S / "scan_first_page.json"), "--dry-run"])
    assert rc == 2 and env["errors"][0]["code"] == "DB_BUSY"
    assert _tree(wmj_home.root) == before

def test_dry_run_on_never_initialised_home_creates_nothing(tmp_path, monkeypatch, capsys):
    from where_my_job.cli import main as cli_main
    home = tmp_path / "never"
    monkeypatch.setenv("WMJ_HOME", str(home))
    rc = cli_main.main(["scan", "--strategy", str(S / "scan_first_page.json"), "--dry-run"])
    env = json.loads(capsys.readouterr().out)
    assert rc == 0 and env["data"]["budget"]["remaining_24h"] == 80 and not home.exists()

def test_dry_run_84_pages_exit_1(cli):
    rc, env, _ = cli(["scan", "--strategy", str(S / "scan_matrix_84.json"), "--dry-run"])
    assert rc == 1 and env["errors"][0]["code"] == "SEMANTIC_INVALID"

def test_dry_run_bad_pause_exit_1(cli):
    rc, env, _ = cli(["scan", "--strategy", str(S / "scan_bad_pause.json"), "--dry-run"])
    assert rc == 1 and env["errors"][0]["path"] == "$.budget.pause_between_actions_sec[0]"

def test_dry_run_in_cooldown_exit_3(cli, wmj_home, clock):
    c = db.open_db(wmj_home.db_path, clock=clock); db.migrate(c, wmj_home)
    with db.write_tx(c):
        Ledger(c, clock, wmj_home).set_cooldown("risk_response", platform_code=37)
    c.close()
    rc, env, _ = cli(["scan", "--strategy", str(S / "scan_first_page.json"), "--dry-run"])
    assert rc == 3 and env["errors"][0]["code"] == "COOLDOWN_ACTIVE" and env["retry"]["not_before"]

def test_dry_run_clock_rollback_exit_3(cli, wmj_home, clock):
    c = db.open_db(wmj_home.db_path, clock=clock); db.migrate(c, wmj_home)
    with db.write_tx(c):
        Ledger(c, clock, wmj_home).reserve("list_page", run_id="earlier")
    c.close()
    rewind_wall(clock, 600)
    rc, env, _ = cli(["scan", "--strategy", str(S / "scan_first_page.json"), "--dry-run"])
    assert rc == 3 and env["errors"][0]["code"] == "CLOCK_ANOMALY"
