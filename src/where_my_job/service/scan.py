# src/where_my_job/service/scan.py
from __future__ import annotations
import hashlib
from dataclasses import dataclass
from ..adapter.cdp import CdpTransport
from ..adapter.session import BrowserSession
from ..config.loader import load_json_file
from ..errors import WmjError, EnvError, Partial
from ..launcher.chrome import ChromeLauncher
from ..normalize.api import map_api_entry, ApiEntryError
from ..paths import Layout, home
from ..policy.gate import Gate, validate_pause
from ..policy.layout import checked_network_layout, profile_id_for
from ..policy.ledger import BUDGET_24H, PolicyView, actions_in_window, check_view
from ..public_messages import public_message
from ..store import db, runs, companies, jobs, sightings, policy as policy_store
from . import network_run
from .bootstrap import with_context
from .online_gate import require_online_enabled
from .scan_plan import expand_plan

def dry_run(lay: Layout, clock, strategy_path: str) -> dict:
    """不打开可写连接、不迁移、不建目录、不写账本或 run。"""
    strategy = load_json_file(strategy_path, "strategy")
    plan = expand_plan(strategy)
    validate_pause(plan.pause)
    net = checked_network_layout(lay)
    view = PolicyView.from_state(policy_store.read_state_readonly(net.db_path, profile_id_for(net.browser_profile)))
    now = clock.now()
    check_view(view, now, plan.actions)
    return {
        "dry_run": True, "strategy": plan.name, "planned_actions": plan.actions,
        "tasks": [{"task_key": t.task_key, "keyword": t.keyword, "city": t.city, "city_code": t.city_code,
                   "page": t.page, "filters": dict(t.filters), "filter_labels": dict(t.filter_labels)} for t in plan.tasks],
        "budget": {"remaining_24h": BUDGET_24H - actions_in_window(view, now), "budget_24h": BUDGET_24H,
                   "cooldown_until": view.cooldown_until},
        "estimated_seconds": plan.estimated_seconds(),
        "note": "服务端筛选已过滤的岗位不能靠本地恢复；面板显示本次采样条件",
    }

def make_transport(ctx):
    verified = ChromeLauncher(ctx.home).verify()
    return CdpTransport.open(verified.ws_url)

def blank_check(ctx) -> None:
    lch = ChromeLauncher(ctx.home)
    lch.blank_check(lch.verify())

def make_pacing(ctx):
    return None, None                         # Gate 使用 time.sleep 与 random.uniform

@dataclass(frozen=True)
class SaveResult:
    inserted: int
    skipped_existing: int
    valid: int
    record_errors: tuple
    job_ids: frozenset
    response_key: str

def response_key_for(task_id: str, page: int, request_id: str) -> str:
    return hashlib.sha256(f"{task_id}|{page}|{request_id}".encode("utf-8")).hexdigest()[:32]

def save_response(ctx, run_id: str, task_id: str, *, page: int, request_id: str, items: list) -> SaveResult:
    """一个响应一个写事务：写有效条目 → 刷新本响应触及的岗位 → 结束任务并记录 response_key 与计数。
    幂等只认同一来源唯一键 (task_id, response_key, item_index)；其它约束失败整体回滚。"""
    key = response_key_for(task_id, page, request_id)
    inserted = skipped = valid = 0
    errors: list[dict] = []
    touched: set[str] = set()
    try:
        with db.write_tx(ctx.conn):
            for idx, raw in enumerate(items):
                try:
                    m = map_api_entry(raw)
                except ApiEntryError:
                    errors.append({"item_index": idx, "reason": "invalid_entry"})
                    continue
                valid += 1
                if sightings.exists_capture_key(ctx.conn, task_id, key, idx):
                    skipped += 1
                    continue
                if m.company_id:
                    companies.ensure(ctx.conn, ctx.clock, m.company_id, "boss", m.company_id.split(":", 1)[1], m.company_name)
                jobs.ensure(ctx.conn, ctx.clock, m.job_id, "boss", m.source_job_id, None, m.company_id)
                sightings.insert(ctx.conn, ctx.clock, job_id=m.job_id, run_id=run_id, task_id=task_id, response_key=key,
                                 item_index=idx, page=page, observed_at=ctx.clock.now(), observed_at_raw=None,
                                 time_precision="response", tz_assumption=None, raw_kind="api_entry",
                                 raw=m.raw_private, fact=m.fact)
                touched.add(m.job_id)
                inserted += 1
            for job_id in touched:
                jobs.refresh_current(ctx.conn, ctx.clock, job_id)
            runs.finish_task(ctx.conn, ctx.clock, task_id, status="ok", response_key=key)
            runs.merge_task_query(ctx.conn, task_id, {"response_key": key, "inserted": inserted,
                                                      "skipped_existing": skipped, "record_errors": errors})
    except WmjError:
        raise
    except Exception as exc:                                  # noqa: BLE001
        mapped = db.map_sqlite_error(exc)          # 01 对非 SQLite 异常返回 None
        if mapped is None:
            raise EnvError("INTERNAL", "保存响应时出现未预期错误") from None
        raise mapped from None
    return SaveResult(inserted, skipped, valid, tuple(errors), frozenset(touched), key)

_COUNTS = ("planned", "completed", "saved_observations", "saved_jobs", "empty_tasks", "record_errors",
           "ignored_responses", "refused_subframes")

def _fail_and_skip(ctx, st, task_id: str, status: str, code: str, reason: str) -> None:
    with db.write_tx(ctx.conn):
        runs.finish_task(ctx.conn, ctx.clock, task_id, status=status, failure_code=code, failure_message=reason)
        runs.skip_planned(ctx.conn, ctx.clock, st.run_id, "stopped_after_failure")

def _scan_body(ctx, gate: Gate, plan, st) -> dict:
    st.summary.update({k: 0 for k in _COUNTS})
    st.summary["ignored_reasons"] = {}
    st.summary["planned"] = plan.actions
    with db.write_tx(ctx.conn):
        ids = runs.add_planned_tasks(ctx.conn, ctx.clock, st.run_id, [
            (t.task_key, {"keyword": t.keyword, "city_code": t.city_code, "filters": dict(t.filters),
                          "filter_labels": dict(t.filter_labels), "page": t.page}) for t in plan.tasks])
    transport = make_transport(ctx)
    st.closers.append(transport.close)
    session = BrowserSession(transport)
    touched: set[str] = set()
    groups: dict[tuple, list] = {}
    for t in plan.tasks:
        groups.setdefault((t.keyword, t.city_code, tuple(sorted(t.filters.items()))), []).append(t)
    for tasks in groups.values():
        tasks = sorted(tasks, key=lambda x: x.page)
        for i, task in enumerate(tasks):
            task_id = ids[task.task_key]
            rest = [ids[x.task_key] for x in tasks[i + 1:]]
            gate.reserve("list_page", st.run_id)
            res = (session.search_page(task.keyword, task.city_code, task.page, dict(task.filters)) if i == 0
                   else session.next_page(task.page))
            st.summary["ignored_responses"] += res.ignored_responses
            for code, n in res.ignored_reasons.items():
                st.summary["ignored_reasons"][code] = st.summary["ignored_reasons"].get(code, 0) + n
            st.summary["refused_subframes"] += res.refused_subframes
            st.summary["documents"] = (st.summary.get("documents", []) + list(res.notes))[:8]
            if res.kind == "blocked":
                # 顺序固定：冷却先单独提交，再尽力记任务；记任务失败只留 warning，仍以 Blocked 退出 3
                blocked = gate.persist_block(st.run_id, reason_code=res.reason, platform_code=res.platform_code,
                                             data={k: st.summary[k] for k in _COUNTS})
                network_run.best_effort_write(
                    ctx, lambda: _fail_and_skip(ctx, st, task_id, "blocked", "RISK_DETECTED", res.reason))
                raise blocked
            if res.kind in ("unauthenticated", "unknown"):
                code = "UNAUTHENTICATED" if res.kind == "unauthenticated" else "CAPTURE_FAILED"
                _fail_and_skip(ctx, st, task_id, "failed", code, res.reason)
                raise EnvError(code, public_message(code))
            if res.kind == "empty":
                with db.write_tx(ctx.conn):
                    runs.finish_task(ctx.conn, ctx.clock, task_id, status="empty")
                    runs.skip_planned(ctx.conn, ctx.clock, st.run_id, "no_more_results", rest)
                st.completed += 1
                st.summary["completed"] = st.completed
                st.summary["empty_tasks"] += 1
                break
            saved = save_response(ctx, st.run_id, task_id, page=task.page, request_id=res.request_id,
                                  items=res.classified.items)
            st.committed += saved.inserted
            st.completed += 1
            touched |= saved.job_ids
            st.summary.update(completed=st.completed, saved_observations=st.committed, saved_jobs=len(touched))
            st.summary["record_errors"] += len(saved.record_errors)
            if res.classified.items and saved.valid == 0:
                with db.write_tx(ctx.conn):
                    runs.skip_planned(ctx.conn, ctx.clock, st.run_id, "stopped_after_failure")
                raise EnvError("CAPTURE_FAILED", public_message("CAPTURE_FAILED"))
            if res.classified.has_more is not True:
                reason = "no_more_results" if res.classified.has_more is False else "has_more_unknown"
                with db.write_tx(ctx.conn):
                    runs.skip_planned(ctx.conn, ctx.clock, st.run_id, reason, rest)
                break
    if st.summary["record_errors"]:
        raise Partial("PARTIAL_RESULT", public_message("PARTIAL_RESULT"))
    out = {k: st.summary[k] for k in _COUNTS}
    out["documents"] = st.summary.get("documents", [])
    out["ignored_reasons"] = dict(sorted(st.summary["ignored_reasons"].items()))
    return out

def run(ctx, strategy_path: str) -> tuple[dict, str]:
    require_online_enabled(ctx)
    blank_check(ctx)                   # 展开计划之前就确认浏览器可用，避免白占一次 list_page 动作
    strategy = load_json_file(strategy_path, "strategy")
    plan = expand_plan(strategy)
    sleep, rng = make_pacing(ctx)
    gate = Gate(ctx, pause=plan.pause, sleep=sleep, rng=rng)
    config = {"strategy": strategy, "task_keys": [t.task_key for t in plan.tasks], "probe": False}
    out = network_run.execute(ctx, gate, actions=plan.actions, kind="scan", config=config,
                              body=lambda st: _scan_body(ctx, gate, plan, st))
    if out.primary is not None:
        raise out.primary
    return out.data, out.run_id

def register(sub, set_handler):
    p = sub.add_parser("scan", help="按策略受控采集列表页；--dry-run 只展开计划，不联网、不写任何状态")
    p.add_argument("--strategy", required=True)
    p.add_argument("--dry-run", action="store_true")
    def handle(ns, warnings):
        if ns.dry_run:
            from ..cli import main as cli_main
            return dry_run(Layout(home()), cli_main.make_clock(), ns.strategy)
        return with_context(ns, warnings, lambda ctx: run(ctx, ns.strategy), write=True)
    set_handler(p, "scan", handle)
