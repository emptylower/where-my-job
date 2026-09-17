"""所有创建 run 的在线入口共用的生命周期。顺序固定：
只读前置检查 → 持锁复查 → runs.create_owned → try 执行 → except 记录主错误 → finally 关闭资源 → 落终态 → 返回。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
from ..errors import WmjError, Blocked, Partial, EnvError
from ..public_messages import public_message
from ..store import db, runs

@dataclass
class RunState:
    run_id: str
    committed: int = 0                        # 已提交的观察或证据条数
    completed: int = 0                        # 已成功完成的任务数
    summary: dict = field(default_factory=dict)   # 只放计数与固定原因码
    closers: list[Callable[[], None]] = field(default_factory=list)

@dataclass
class NetworkOutcome:
    run_id: str
    data: object
    primary: WmjError | None
    state: RunState

def _status(primary: WmjError | None) -> str:
    if primary is None:
        return "ok"
    if isinstance(primary, Blocked):
        return "blocked"
    if isinstance(primary, Partial):
        return "partial"
    return "failed"

POST_BLOCK_WARNING = "风控冷却已记录，但任务或 run 状态写入失败，已忽略"

def best_effort_write(ctx, fn: Callable[[], None]) -> None:
    """冷却提交之后的任务/run 记账：失败只留固定 warning，不改变主错误，也不外泄异常文本。"""
    try:
        fn()
    except Exception as exc:                              # noqa: BLE001
        ctx.log(f"post-block bookkeeping failure: {type(exc).__name__}")
        ctx.warnings.append(POST_BLOCK_WARNING)

def execute(ctx, gate, *, actions: int, kind: str, config: dict, body: Callable[[RunState], object],
            finish: bool = True) -> NetworkOutcome:
    gate.precheck(actions)
    with gate.hold(actions):
        run_id = runs.create_owned(ctx, kind=kind, config=config, planned=actions)
        st = RunState(run_id)
        data, primary = None, None
        try:
            data = body(st)
        except WmjError as exc:
            primary = exc
        except Exception as exc:                          # noqa: BLE001 — 不外泄异常文本
            ctx.log(f"network run internal failure: {type(exc).__name__}")
            primary = EnvError("INTERNAL", public_message("INTERNAL"))
        finally:
            for close in reversed(st.closers):
                try:
                    close()
                except Exception as exc:                  # noqa: BLE001
                    ctx.log(f"network run cleanup failure: {type(exc).__name__}")
                    ctx.warnings.append("资源清理失败，已忽略")
        if primary is not None and not isinstance(primary, (Blocked, Partial)) and st.committed:
            primary = Partial("PARTIAL_RESULT", public_message("PARTIAL_RESULT"))
        if finish:
            try:
                with db.write_tx(ctx.conn):
                    runs.finish(ctx.conn, ctx.clock, run_id, status=_status(primary),
                                completed=st.completed, summary=st.summary)
            except Exception as exc:                      # noqa: BLE001
                ctx.log(f"network run finish failure: {type(exc).__name__}")
                if primary is None:
                    primary = EnvError("DISK_ERROR", public_message("DISK_ERROR"))
                elif isinstance(primary, Blocked):
                    ctx.warnings.append(POST_BLOCK_WARNING)   # 冷却已提交，仍以 Blocked 退出 3
        if primary is not None:
            primary.run_id = run_id
            primary.data = {**st.summary, **(primary.data or {})}
        return NetworkOutcome(run_id, data, primary, st)
