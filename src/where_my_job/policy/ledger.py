"""滚动 24h 动作账本 + 持久冷却 + 时间高水位。数值是保守产品上限，不是已验证安全配额。"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from ..clock import Clock, iso_utc, parse_iso
from ..errors import Blocked
from ..paths import Layout
from ..public_messages import public_message
from ..store import policy as ps
from .layout import checked_network_layout, profile_id_for

BUDGET_24H = 80
MIN_INTERVAL_SEC = 12
DEFAULT_MAX_INTERVAL_SEC = 22
COOLDOWN_HOURS = 4
WINDOW = timedelta(hours=24)
ACTION_KINDS = ("list_page", "detail_page", "company_page", "probe", "login")

@dataclass(frozen=True)
class PolicyView:
    entries: tuple
    cooldown_until: str | None
    last_action_at: str | None
    updated_at: str | None

    @staticmethod
    def from_state(state: dict | None) -> "PolicyView":
        if state is None:
            return PolicyView((), None, None, None)
        return PolicyView(tuple(state["ledger"]), state["cooldown_until"], state["last_action_at"], state["updated_at"])

def high_water(view: PolicyView) -> datetime | None:
    return parse_iso(view.updated_at) if view.updated_at else None

def actions_in_window(view: PolicyView, now: datetime) -> int:
    cutoff = now - WINDOW
    return sum(1 for e in view.entries if parse_iso(e["at"]) >= cutoff)

def check_view(view: PolicyView, now: datetime, actions: int) -> None:
    """纯函数：时钟 → 冷却 → 额度。任何一项不满足抛 Blocked（退出 3）。"""
    hw = high_water(view)
    if hw is not None and now < hw:
        raise Blocked("CLOCK_ANOMALY", public_message("CLOCK_ANOMALY"), retry={"automatic": False, "not_before": None})
    if view.cooldown_until and now < parse_iso(view.cooldown_until):
        raise Blocked("COOLDOWN_ACTIVE", public_message("COOLDOWN_ACTIVE"),
                      retry={"automatic": False, "not_before": view.cooldown_until})
    remaining = max(0, BUDGET_24H - actions_in_window(view, now))
    if actions > remaining:
        raise Blocked("BUDGET_EXHAUSTED", public_message("BUDGET_EXHAUSTED"),
                      retry={"automatic": False, "not_before": None},
                      data={"planned_actions": actions, "remaining_24h": remaining})

class Ledger:
    """构造只读。reserve/set_cooldown 必须在调用方的 write_tx 内调用。"""
    def __init__(self, conn, clock: Clock, lay: Layout):
        self.conn, self.clock = conn, clock
        self.lay = checked_network_layout(lay)
        self.profile_id = profile_id_for(self.lay.browser_profile)

    def view(self) -> PolicyView:
        return PolicyView.from_state(ps.read_state(self.conn, self.profile_id))

    def check(self, actions: int) -> None:
        check_view(self.view(), self.clock.now(), actions)

    def actions_last_24h(self) -> int:
        return actions_in_window(self.view(), self.clock.now())

    def remaining(self) -> int:
        return max(0, BUDGET_24H - self.actions_last_24h())

    def cooldown_until(self) -> str | None:
        return self.view().cooldown_until

    def reserve(self, kind: str, run_id: str) -> None:
        if kind not in ACTION_KINDS:
            raise ValueError(f"unknown action kind {kind}")
        view = self.view()
        now = self.clock.now()
        check_view(view, now, 1)
        cutoff = now - WINDOW
        entries = [e for e in view.entries if parse_iso(e["at"]) >= cutoff]
        stamp = iso_utc(now)
        entries.append({"at": stamp, "kind": kind, "run_id": run_id})
        hw = high_water(view)
        ps.upsert_ledger(self.conn, self.profile_id, entries, last_action_at=stamp,
                         updated_at=iso_utc(max(now, hw) if hw else now))

    def set_cooldown(self, reason_code: str, platform_code: int | None = None) -> str:
        """reason_code 是固定内部原因码；platform_code 只作整数元数据，不存平台 message。"""
        view = self.view()
        now = self.clock.now()
        hw = high_water(view)
        base = max(now, hw) if hw else now
        until = base + timedelta(hours=COOLDOWN_HOURS)
        if view.cooldown_until and parse_iso(view.cooldown_until) > until:
            until = parse_iso(view.cooldown_until)
        ps.upsert_cooldown(self.conn, self.profile_id, iso_utc(until), reason_code, updated_at=iso_utc(base))
        return iso_utc(until)
