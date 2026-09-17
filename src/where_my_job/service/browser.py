# src/where_my_job/service/browser.py
"""init --browser（只启动，不导航、不计动作）、init --probe（经门禁的一次搜索页）、browser stop。"""
from __future__ import annotations
from ..adapter.cdp import CdpTransport
from ..adapter.session import BrowserSession
from ..config.search_codes import city_code
from ..errors import EnvError
from ..launcher.chrome import ChromeLauncher
from ..policy.gate import Gate
from ..public_messages import public_message
from ..store import db, runs
from . import network_run
from .bootstrap import with_context
from .online_gate import require_online_enabled

PROBE_KEYWORD = "产品经理"
PROBE_CITY = "合肥"

def make_launcher(lay):
    return ChromeLauncher(lay)

def make_transport(ctx, verified):
    return CdpTransport.open(verified.ws_url)

def make_pacing(ctx):
    return None, None

def start_browser(ctx, launcher=None) -> dict:
    require_online_enabled(ctx)
    v = (launcher or make_launcher(ctx.home)).start()
    return {"browser": {"pid": v.state.pid, "port": v.state.port, "started_at": v.state.started_at, "login": "manual"},
            "next_step": "在刚打开的专用 Chrome 中手动登录；本工具不读取 Cookie、不自动导航。登录后可运行 where-my-job init --probe 或 scan --dry-run"}

def probe(ctx, launcher=None) -> tuple[dict, str]:
    require_online_enabled(ctx)
    lch = launcher or make_launcher(ctx.home)
    verified = lch.verify()                                       # 未验证归属前不占额度、不建 run
    lch.blank_check(verified)                                     # 浏览器里有别的标签页时，也在建 run 与占额度之前停
    sleep, rng = make_pacing(ctx)
    gate = Gate(ctx, sleep=sleep, rng=rng)
    code = city_code(PROBE_CITY)
    def body(st):
        with db.write_tx(ctx.conn):
            task_id = runs.add_planned_tasks(ctx.conn, ctx.clock, st.run_id, [
                ("probe", {"keyword": PROBE_KEYWORD, "city_code": code, "page": 1, "probe": True})])["probe"]
        gate.reserve("probe", st.run_id)
        transport = make_transport(ctx, verified)
        st.closers.append(transport.close)
        res = BrowserSession(transport).search_page(PROBE_KEYWORD, code, 1, {})
        st.summary["documents"] = list(res.notes)          # 失败时随 run 摘要与 envelope 一起交回，便于离线定位
        st.summary["refused_subframes"] = res.refused_subframes
        st.summary["ignored_responses"] = res.ignored_responses   # 区分"接口没发出"与"发了但不属于本次动作"
        st.summary["ignored_reasons"] = dict(res.ignored_reasons) # 哪一项不符：端点、参数、文档还是会话；不含地址与内容
        st.summary["reason"] = res.reason                         # 本工具的固定内部原因码，不含页面内容
        if res.kind == "blocked":
            blocked = gate.persist_block(st.run_id, reason_code=res.reason, platform_code=res.platform_code)  # 冷却先单独提交

            def bookkeep() -> None:
                with db.write_tx(ctx.conn):
                    runs.finish_task(ctx.conn, ctx.clock, task_id, status="blocked", failure_code="RISK_DETECTED", failure_message=res.reason)
            network_run.best_effort_write(ctx, bookkeep)
            raise blocked
        if res.kind in ("unauthenticated", "unknown"):
            err = "UNAUTHENTICATED" if res.kind == "unauthenticated" else "CAPTURE_FAILED"
            with db.write_tx(ctx.conn):
                runs.finish_task(ctx.conn, ctx.clock, task_id, status="failed", failure_code=err, failure_message=res.reason)
            raise EnvError(err, public_message(err))
        with db.write_tx(ctx.conn):
            runs.finish_task(ctx.conn, ctx.clock, task_id, status="ok" if res.kind == "success" else "empty")
        st.completed = 1
        result = {"kind": res.kind, "login": "available" if res.kind == "success" else "unconfirmed_empty",
                  "has_more": res.classified.has_more, "item_count": len(res.classified.items)}
        st.summary["probe"] = result
        return {"probe": result, "documents": list(res.notes), "refused_subframes": res.refused_subframes,
                "ignored_responses": res.ignored_responses, "ignored_reasons": dict(res.ignored_reasons),
                "reason": res.reason}
    out = network_run.execute(ctx, gate, actions=1, kind="scan",
                              config={"probe": True, "keyword": PROBE_KEYWORD, "city_code": code}, body=body)
    if out.primary is not None:
        raise out.primary
    data = dict(out.data)
    data["budget_remaining_24h"] = gate.ledger.remaining()
    return data, out.run_id

def stop_browser(ctx, launcher=None) -> dict:
    return (launcher or make_launcher(ctx.home)).stop()

def register(sub, set_handler):
    p = sub.add_parser("browser", help="专用浏览器管理")
    s = p.add_subparsers(dest="browser_cmd"); s.required = True
    st = s.add_parser("stop", help="只停止能证明归属于本工具的专用 Chrome，并确认已退出")
    set_handler(st, "browser stop", lambda ns, w: with_context(ns, w, lambda ctx: stop_browser(ctx), write=True))
