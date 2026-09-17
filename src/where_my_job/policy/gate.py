"""受控网络动作的唯一入口：scan / deepdive / probe 都经这里。"""
from __future__ import annotations
import random, time
from contextlib import contextmanager
from typing import Callable, NoReturn
from ..clock import parse_iso
from ..errors import Blocked, InvalidInput, ErrorItem
from ..public_messages import public_message
from ..store import db
from .ledger import Ledger, check_view, MIN_INTERVAL_SEC, DEFAULT_MAX_INTERVAL_SEC
from .lock import BrowserLock

def validate_pause(pause) -> tuple[float, float]:
    """策略间隔只能收紧：下限不低于 12 秒，上限不小于下限。dry-run 与 Gate 共用。"""
    lo, hi = float(pause[0]), float(pause[1])
    if lo < MIN_INTERVAL_SEC or hi < lo:
        raise InvalidInput([ErrorItem("SEMANTIC_INVALID", f"间隔下限不得低于 {MIN_INTERVAL_SEC} 秒且上限不小于下限",
                                      "$.budget.pause_between_actions_sec")])
    return lo, hi

class Gate:
    def __init__(self, ctx, *, pause: tuple[float, float] = (MIN_INTERVAL_SEC, DEFAULT_MAX_INTERVAL_SEC),
                 sleep: Callable[[float], None] | None = None, rng: Callable[[float, float], float] | None = None):
        lo, hi = validate_pause(pause)
        self.ctx = ctx
        self.pause = (lo, hi)
        self.ledger = Ledger(ctx.conn, ctx.clock, ctx.home)
        self.lock = BrowserLock(ctx.home)
        self.sleep = sleep or time.sleep
        self.rng = rng or random.uniform
        self._last_mono: float | None = None

    def precheck(self, actions: int) -> None:
        """无副作用：时钟、冷却、整个计划的额度。"""
        self.ledger.check(actions)

    @contextmanager
    def hold(self, actions: int):
        with self.lock:
            self.ledger.check(actions)          # 持锁后完整复查
            yield self

    def reserve(self, kind: str, run_id: str) -> None:
        if not self.lock.held:
            raise RuntimeError("reserve() must be called inside gate.hold()")
        now = self.ctx.clock.now()
        view = self.ledger.view()
        check_view(view, now, 1)
        target = max(float(MIN_INTERVAL_SEC), float(self.rng(*self.pause)))
        if self._last_mono is not None:
            elapsed = self.ctx.clock.monotonic() - self._last_mono
        elif view.last_action_at:
            elapsed = (now - parse_iso(view.last_action_at)).total_seconds()
        else:
            elapsed = None
        wait = 0.0 if elapsed is None else max(0.0, target - elapsed)
        if wait > 0:
            self.sleep(wait)
        with db.write_tx(self.ctx.conn):
            self.ledger.reserve(kind, run_id)   # 事务内再次核对时钟、冷却与额度
        self._last_mono = self.ctx.clock.monotonic()

    def persist_block(self, run_id: str, *, reason_code: str, platform_code: int | None = None,
                      data: dict | None = None) -> Blocked:
        """先在独立短事务里提交冷却，再构造（不抛出）Blocked。
        调用方随后尽力记录任务与 run，最后 `raise` 返回值；记账失败不能让冷却丢失。"""
        with db.write_tx(self.ctx.conn):
            until = self.ledger.set_cooldown(reason_code, platform_code)
        return Blocked("RISK_DETECTED", public_message("RISK_DETECTED"),
                       retry={"automatic": False, "not_before": until},
                       data={"reason": reason_code, "platform_code": platform_code, **(data or {})})

    def record_block(self, run_id: str, *, reason_code: str, platform_code: int | None = None,
                     data: dict | None = None) -> NoReturn:
        raise self.persist_block(run_id, reason_code=reason_code, platform_code=platform_code, data=data)
