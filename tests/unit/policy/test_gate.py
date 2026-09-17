import pytest
from where_my_job.errors import Blocked, InvalidInput
from where_my_job.policy.gate import Gate
from where_my_job.policy.ledger import BUDGET_24H, MIN_INTERVAL_SEC
from where_my_job.store import db
from tests.helpers.sleeper import Sleeper, rewind_wall

def test_precheck_is_read_only_and_checks_whole_plan(ctx):
    g = Gate(ctx, sleep=Sleeper(ctx.clock), rng=lambda lo, hi: lo)
    g.precheck(BUDGET_24H)
    with pytest.raises(Blocked) as ei:
        g.precheck(BUDGET_24H + 1)
    assert ei.value.code == "BUDGET_EXHAUSTED"
    assert ctx.conn.execute("select count(*) from network_policy_state").fetchone()[0] == 0

def test_hold_rechecks_and_second_gate_is_busy(ctx):
    g1 = Gate(ctx, sleep=Sleeper(ctx.clock)); g2 = Gate(ctx, sleep=Sleeper(ctx.clock))
    with g1.hold(1):
        with pytest.raises(Blocked) as ei:
            with g2.hold(1):
                pass
    assert ei.value.code == "RESOURCE_BUSY"

def test_reserve_paces_within_run(ctx):
    sl = Sleeper(ctx.clock)
    g = Gate(ctx, sleep=sl, rng=lambda lo, hi: lo)
    with g.hold(2):
        g.reserve("list_page", "r"); g.reserve("list_page", "r")
    assert sl.calls == [float(MIN_INTERVAL_SEC)] and g.ledger.actions_last_24h() == 2

def test_new_run_respects_slower_strategy_from_last_persisted_action(ctx):
    g1 = Gate(ctx, sleep=Sleeper(ctx.clock), rng=lambda lo, hi: lo)
    with g1.hold(1):
        g1.reserve("list_page", "r1")
    ctx.clock.advance(5)
    sl = Sleeper(ctx.clock)
    g2 = Gate(ctx, pause=(30, 40), sleep=sl, rng=lambda lo, hi: lo)
    with g2.hold(1):
        g2.reserve("list_page", "r2")
    assert sl.calls == [25.0]

def test_pause_floor_is_enforced(ctx):
    with pytest.raises(InvalidInput) as ei:
        Gate(ctx, pause=(5, 22))
    assert ei.value.path == "$.budget.pause_between_actions_sec"

def test_wall_clock_rollback_during_wait_blocks_without_reservation(ctx):
    g1 = Gate(ctx, sleep=Sleeper(ctx.clock), rng=lambda lo, hi: lo)
    with g1.hold(1):
        g1.reserve("list_page", "r")
    sl = Sleeper(ctx.clock, on_sleep=lambda s: rewind_wall(ctx.clock, 3600))
    g2 = Gate(ctx, sleep=sl, rng=lambda lo, hi: lo)
    ctx.clock.advance(1)
    with g2.hold(1):
        with pytest.raises(Blocked) as ei:
            g2.reserve("list_page", "r")
    assert ei.value.code == "CLOCK_ANOMALY" and g2.ledger.view().entries.__len__() == 1

def test_cooldown_blocks_reserve(ctx):
    g = Gate(ctx, sleep=Sleeper(ctx.clock))
    with db.write_tx(ctx.conn):
        g.ledger.set_cooldown("risk_response", platform_code=37)
    with pytest.raises(Blocked) as ei:
        g.precheck(1)
    assert ei.value.code == "COOLDOWN_ACTIVE" and ei.value.retry == {"automatic": False, "not_before": g.ledger.cooldown_until()}

def test_record_block_sets_cooldown_with_fixed_message(ctx):
    g = Gate(ctx, sleep=Sleeper(ctx.clock))
    with g.hold(1):
        g.reserve("list_page", "r")
        with pytest.raises(Blocked) as ei:
            g.record_block("r", reason_code="risk_response", platform_code=31, data={"saved_observations": 2})
    assert ei.value.code == "RISK_DETECTED" and ei.value.message == "检测到平台访问限制，已停止并进入冷却"
    assert ei.value.data == {"reason": "risk_response", "platform_code": 31, "saved_observations": 2}
    assert ei.value.retry["not_before"] == g.ledger.cooldown_until()

def test_persist_block_commits_cooldown_before_returning_error(ctx):
    g = Gate(ctx, sleep=Sleeper(ctx.clock))
    with g.hold(1):
        g.reserve("list_page", "r")
        err = g.persist_block("r", reason_code="risk_response", platform_code=37)
        assert g.ledger.cooldown_until() is not None and not ctx.conn.in_transaction   # 返回前冷却已提交
    assert isinstance(err, Blocked) and err.exit_code == 3 and err.code == "RISK_DETECTED"
    assert err.retry["not_before"] == g.ledger.cooldown_until()
