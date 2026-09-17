import json
import pytest
from where_my_job.errors import Blocked, EnvError, Partial
from where_my_job.policy.gate import Gate
from where_my_job.service.network_run import execute
from tests.helpers.sleeper import Sleeper

SENTINEL = "LEAK-SENTINEL https://www.zhipin.com/job_detail/x.html?securityId=LEAK SYN-LEAK-SENTINEL-PHONE"

def _gate(ctx):
    return Gate(ctx, sleep=Sleeper(ctx.clock), rng=lambda lo, hi: lo)

def _run_row(ctx, run_id):
    return ctx.conn.execute("select status, summary_json from runs where run_id=?", (run_id,)).fetchone()

def test_success_finishes_ok_and_runs_closers(ctx):
    closed = []
    def body(st):
        st.closers.append(lambda: closed.append(1)); st.completed = 1; st.summary["n"] = 1
        return {"n": 1}
    out = execute(ctx, _gate(ctx), actions=1, kind="scan", config={}, body=body)
    assert out.primary is None and out.data == {"n": 1} and closed == [1]
    assert _run_row(ctx, out.run_id)["status"] == "ok"

def test_blocked_wins_over_cleanup_failure(ctx):
    def body(st):
        def bad_close(): raise RuntimeError(SENTINEL)
        st.closers.append(bad_close); st.committed = 2
        raise Blocked("RISK_DETECTED", "检测到平台访问限制，已停止并进入冷却")
    out = execute(ctx, _gate(ctx), actions=1, kind="scan", config={}, body=body)
    assert isinstance(out.primary, Blocked) and out.primary.exit_code == 3
    assert _run_row(ctx, out.run_id)["status"] == "blocked"
    assert SENTINEL not in json.dumps(ctx.warnings, ensure_ascii=False)

def test_env_failure_after_commit_becomes_partial(ctx):
    def body(st):
        st.committed = 3
        raise EnvError("CAPTURE_FAILED", "未取得可验证的页面响应且没有已保存结果，已停止")
    out = execute(ctx, _gate(ctx), actions=1, kind="scan", config={}, body=body)
    assert isinstance(out.primary, Partial) and out.primary.code == "PARTIAL_RESULT" and out.primary.exit_code == 4
    assert _run_row(ctx, out.run_id)["status"] == "partial"

def test_env_failure_without_commit_stays_exit_2(ctx):
    def body(st):
        raise EnvError("CAPTURE_FAILED", "未取得可验证的页面响应且没有已保存结果，已停止")
    out = execute(ctx, _gate(ctx), actions=1, kind="scan", config={}, body=body)
    assert out.primary.code == "CAPTURE_FAILED" and out.primary.exit_code == 2
    assert _run_row(ctx, out.run_id)["status"] == "failed"

def test_unexpected_exception_is_internal_without_text(ctx):
    def body(st):
        raise ValueError(SENTINEL)
    out = execute(ctx, _gate(ctx), actions=1, kind="scan", config={}, body=body)
    assert out.primary.code == "INTERNAL" and SENTINEL not in out.primary.message
    assert SENTINEL not in _run_row(ctx, out.run_id)["summary_json"]

def test_finish_false_leaves_run_running(ctx):
    out = execute(ctx, _gate(ctx), actions=1, kind="deepdive", config={}, body=lambda st: {}, finish=False)
    assert _run_row(ctx, out.run_id)["status"] == "running"

def test_precheck_failure_creates_no_run(ctx):
    g = _gate(ctx)
    with pytest.raises(Blocked):
        execute(ctx, g, actions=81, kind="scan", config={}, body=lambda st: {})
    assert ctx.conn.execute("select count(*) from runs").fetchone()[0] == 0
