import json
from datetime import timedelta
import pytest
from where_my_job.clock import iso_utc
from where_my_job.errors import Blocked
from where_my_job.store import db, policy as policy_store
from where_my_job.policy.layout import checked_network_layout, profile_id_for
from where_my_job.policy.ledger import Ledger, PolicyView, check_view, BUDGET_24H, COOLDOWN_HOURS
from tests.helpers.sleeper import rewind_wall

def _rows(conn):
    return conn.execute("select count(*) from network_policy_state").fetchone()[0]

def test_constructor_is_read_only_and_derives_profile_id(conn, clock, wmj_home):
    led = Ledger(conn, clock, wmj_home)
    assert _rows(conn) == 0
    assert led.profile_id == profile_id_for(checked_network_layout(wmj_home).browser_profile)
    assert led.remaining() == BUDGET_24H and led.cooldown_until() is None and _rows(conn) == 0

def test_reserve_counts_rolling_window(conn, clock, wmj_home):
    led = Ledger(conn, clock, wmj_home)
    with db.write_tx(conn):
        for _ in range(3): led.reserve("list_page", run_id="run_a")
    clock.advance(23 * 3600)
    with db.write_tx(conn):
        led.reserve("detail_page", run_id="run_b")
    assert led.actions_last_24h() == 4
    clock.advance(2 * 3600)
    assert led.actions_last_24h() == 1 and led.remaining() == BUDGET_24H - 1

def test_eighty_first_action_rejected(conn, clock, wmj_home):
    led = Ledger(conn, clock, wmj_home)
    with db.write_tx(conn):
        for _ in range(BUDGET_24H): led.reserve("list_page", run_id="r")
    with pytest.raises(Blocked) as ei:
        with db.write_tx(conn):
            led.reserve("list_page", run_id="r")
    assert ei.value.code == "BUDGET_EXHAUSTED" and led.actions_last_24h() == BUDGET_24H

def test_no_refund_interface_and_rollback_is_transactional(conn, clock, wmj_home):
    led = Ledger(conn, clock, wmj_home)
    with pytest.raises(RuntimeError):
        with db.write_tx(conn):
            led.reserve("list_page", run_id="r")
            raise RuntimeError("boom")
    assert led.actions_last_24h() == 0 and not hasattr(led, "refund")

def test_cooldown_floor_and_merge_with_later_existing(conn, clock, wmj_home):
    led = Ledger(conn, clock, wmj_home)
    with db.write_tx(conn):
        first = led.set_cooldown("risk_response", platform_code=31)
    assert first == iso_utc(clock.now() + timedelta(hours=COOLDOWN_HOURS))
    clock.advance(3600)
    with db.write_tx(conn):
        led.set_cooldown("risk_page")
    assert led.cooldown_until() == iso_utc(clock.now() + timedelta(hours=COOLDOWN_HOURS))
    with pytest.raises(Blocked) as ei:
        led.check(1)
    assert ei.value.code == "COOLDOWN_ACTIVE" and ei.value.retry["not_before"] == led.cooldown_until()
    state = policy_store.read_state(conn, led.profile_id)
    assert state["cooldown_reason"] == "risk_page" and "http" not in json.dumps(state)

def test_clock_rollback_blocks_and_keeps_high_water(conn, clock, wmj_home):
    led = Ledger(conn, clock, wmj_home)
    with db.write_tx(conn):
        led.reserve("list_page", run_id="r")
    hw = policy_store.read_state(conn, led.profile_id)["updated_at"]
    rewind_wall(clock, 3600)
    with pytest.raises(Blocked) as ei:
        led.check(1)
    assert ei.value.code == "CLOCK_ANOMALY" and ei.value.exit_code == 3
    with pytest.raises(Blocked):
        with db.write_tx(conn):
            led.reserve("list_page", run_id="r")
    with db.write_tx(conn):
        until = led.set_cooldown("risk_response", platform_code=37)   # 已观测风险仍须落库
    state = policy_store.read_state(conn, led.profile_id)
    assert state["updated_at"] == hw and until == iso_utc(clock.now() + timedelta(hours=1 + COOLDOWN_HOURS))
    assert led.actions_last_24h() == 1

def test_pure_view_evaluation_matches_db(conn, clock, wmj_home):
    led = Ledger(conn, clock, wmj_home)
    with db.write_tx(conn):
        led.reserve("probe", run_id="r")
    view = led.view()
    assert isinstance(view, PolicyView) and len(view.entries) == 1
    check_view(view, clock.now(), 79)
    with pytest.raises(Blocked):
        check_view(view, clock.now(), 80)

def test_readonly_state_reader_on_missing_db_creates_nothing(tmp_path):
    db_path = tmp_path / "absent" / "x.sqlite3"
    assert policy_store.read_state_readonly(db_path, "p") is None
    assert not db_path.parent.exists()
