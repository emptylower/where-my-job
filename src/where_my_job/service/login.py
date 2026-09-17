# src/where_my_job/service/login.py
"""login start / status / cancel：agent 可驱动的扫码登录，每条命令都很短。
start 打开固定登录页、识别二维码后立即返回；status 在限定秒数内观察页面、二维码失效时按额度刷新；cancel 关闭登录页。
两次命令之间登录页保持打开，由页面自己完成登录。
二维码按原内容重绘为 0600 PNG，并以半块字符画写到 stderr：agent 界面的命令输出区直接显示，不必等模型转述（二维码约 30 秒失效）。
本工具不读 Cookie、不发自有请求；二维码原文不以文本形式进入 stdout、stderr、数据库或日志。"""
from __future__ import annotations
import json
from ..adapter.cdp import CdpTransport
from ..clock import iso_utc, parse_iso
from ..errors import EnvError, ErrorItem, InvalidInput
from ..launcher.chrome import ChromeLauncher
from ..paths import atomic_write_bytes, atomic_write_text
from ..policy.gate import Gate
from ..policy.lock import BrowserLock
from ..public_messages import public_message
from ..store import db, runs
from . import network_run
from .bootstrap import with_context
from .online_gate import require_online_enabled

START_CAPTURE_SEC = 20.0
DEFAULT_STATUS_WAIT_SEC = 30
MAX_STATUS_WAIT_SEC = 90
MAX_REFRESHES = 6
SESSION_MAX_SEC = 600

QR_CAPTION = "扫码登录：用 BOSS 直聘 App 扫描下面的二维码，并在手机上确认（约 30 秒后失效，失效后会换新）"
TEST_QR_CAPTION = "二维码显示自检：用手机相机扫描下面这张测试码（与 BOSS 无关，不联网）"
TEST_QR_PAYLOAD = "where-my-job 二维码自检".encode("utf-8")

NEXT_SHOW_QR = ("二维码已经显示在专用 Chrome 窗口里，窗口已置前：用一句话请用户扫那个窗口里的二维码并在手机上确认，"
                "然后马上运行 where-my-job login status --wait 30。"
                "命令输出里的字符画只是备用显示，终端界面才提；不要把二维码抄进回复，"
                "也不要只给图片路径或用读图工具代替。`data.login.window_raised` 为 false 时，多提一句请用户切到那个 Chrome 窗口")
NEXT_QR_UPDATED = ("旧二维码已失效，新的已经显示在专用 Chrome 窗口里：用一句话提醒用户扫新的，"
                   "然后马上运行 where-my-job login status --wait 30")
NEXT_WAITING = ("用户还没有确认：不要重复说话，继续运行 where-my-job login status --wait 30，直到 status 为 confirmed；"
                "用户说看不到二维码时运行 where-my-job login status --wait 0 --show-qr，它会把窗口重新置前并重画一次字符画"
                "（浅色背景终端再加 --light-terminal）")
NEXT_NO_QR = ("本工具没能从页面上识别出二维码，但登录页就开在专用 Chrome 窗口里："
              "请用户直接扫那个窗口，然后运行 where-my-job login status --wait 30")
NEXT_DONE = "登录已完成：用一句话告诉用户已登录，然后继续当前场景的下一步"
NEXT_TEST_QR = ("请用户按 ctrl+o 展开这条命令的输出，用手机相机扫这张测试码；扫得出来就照这个画法继续，"
                "扫不出来换一种：where-my-job login test-qr --light-terminal（浅色背景终端）。"
                "确定后把 qr_terminal_background 写进数据目录的 settings.json（light 或 dark），之后不必再带参数")

def make_launcher(lay):
    return ChromeLauncher(lay)

def make_transport(ctx, verified):
    return CdpTransport.open(verified.ws_url)

def make_attach_transport(ctx, verified, target_id):
    return CdpTransport.open(verified.ws_url, target_id=target_id)

def make_pacing(ctx):
    return None, None

# ---- 会话状态 ----
def _state_path(lay):
    return lay.state / "login.json"

def _qr_path(lay):
    return lay.state / "login-qr.png"

def _read_state(lay) -> dict | None:
    try:
        obj = json.loads(_state_path(lay).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    ok = (isinstance(obj, dict) and isinstance(obj.get("target_id"), str) and isinstance(obj.get("run_id"), str)
          and isinstance(obj.get("started_at"), str) and isinstance(obj.get("refreshes"), int)
          and (obj.get("qr_digest") is None or isinstance(obj.get("qr_digest"), str)))
    return obj if ok else None

def _write_state(lay, state: dict) -> None:
    atomic_write_text(_state_path(lay), json.dumps(state, sort_keys=True), lay=lay)

def _clear(lay) -> None:
    for path in (_state_path(lay), _qr_path(lay)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

def _draw_qr(ctx, payload: bytes, caption: str, light_terminal: bool) -> None:
    """把一行提示和二维码画到 stderr：stderr 是终端时用带颜色的半块字符；
    否则（agent 的命令输出区）用不带颜色控制符的半块字符，默认按深色背景画。"""
    from ..adapter import qr
    stream = ctx.stderr
    if stream is None:
        return
    if getattr(stream, "isatty", lambda: False)():
        drawing = qr.render_terminal(payload)
    else:
        drawing = "\n".join(qr.text_lines(payload, light_terminal=light_terminal))
    stream.write(caption + "\n" + drawing + "\n")
    stream.flush()

def _light_terminal(ctx, light: bool, dark: bool) -> bool:
    """命令行参数优先；否则读数据目录 settings.json 的 qr_terminal_background；读不到按深色背景画。"""
    if light:
        return True
    if dark:
        return False
    try:
        path = ctx.home.config("settings.json")
        if not path.exists():
            return False
        from ..config.loader import load_json_file
        return load_json_file(path, "settings").get("qr_terminal_background") == "light"
    except Exception:                                     # noqa: BLE001 — 配置有问题不影响登录，按默认画法
        return False

def _save_qr(ctx, payload: bytes, *, light_terminal: bool = False) -> str:
    """写 0600 PNG，并把二维码画到 stderr。"""
    from ..adapter import qr
    path = _qr_path(ctx.home)
    atomic_write_bytes(path, qr.png_bytes(payload), lay=ctx.home)
    _draw_qr(ctx, payload, QR_CAPTION, light_terminal)
    return str(path)

def test_qr(ctx, *, light_terminal: bool = False) -> dict:
    """只画一张固定内容的测试码，用来确认 agent 界面与终端底色下二维码能不能被扫出来。不联网、不计动作、不写文件。"""
    _draw_qr(ctx, TEST_QR_PAYLOAD, TEST_QR_CAPTION, light_terminal)
    return {"login": {"status": "test_drawing", "light_terminal": light_terminal, "next_step": NEXT_TEST_QR}}

def _view(status: str, state: dict | None, next_step: str, qr_png: str | None, notes: list | None = None,
          surface: str | None = None, window_raised: bool | None = None) -> dict:
    """surface 是给 agent 的机器可读依据：扫码面在哪。
    `browser` = 登录页就开在专用 Chrome 窗口里（二维码本来就是从那个窗口截下来的，用户扫窗口一定有效）；
    window_raised = 本工具有没有成功把那个窗口提到前台。两者都为 None 表示当前没有可扫的登录页。"""
    return {"login": {"status": status, "qr_png": qr_png, "refreshes": (state or {}).get("refreshes", 0),
                      "notes": list(notes or []), "surface": surface, "window_raised": window_raised,
                      "next_step": next_step}}

def _login_notes(obs) -> list:
    """只回传本工具自己的常量，不回传页面内容。"""
    return [f"expiry_marker:{obs.expiry_marker}"] if obs.expiry_marker else []

def _close_or_detach(ctx, transport, keep: bool) -> None:
    try:
        if keep:
            transport.detach()
        else:
            transport.close()
    except Exception as exc:                              # noqa: BLE001
        ctx.log(f"login transport cleanup failure: {type(exc).__name__}")
        ctx.warnings.append("资源清理失败，已忽略")

# ---- 命令 ----
def start(ctx, launcher=None, *, light_terminal: bool = False, dark_terminal: bool = False) -> tuple[dict, str | None]:
    require_online_enabled(ctx)
    from ..adapter import login as page_mod
    from ..adapter.qr import payload_digest
    light_terminal = _light_terminal(ctx, light_terminal, dark_terminal)
    sleep, rng = make_pacing(ctx)
    gate = Gate(ctx, sleep=sleep, rng=rng)
    gate.precheck(1)                                      # 冷却、时钟、额度不满足时不启动浏览器
    if _read_state(ctx.home) is not None:
        try:                                              # 登录页仍在：复用并重新画出当前二维码，不再导航
            return status(ctx, wait=0, launcher=launcher, show_qr=True, light_terminal=light_terminal), None
        except EnvError as err:
            if err.code not in ("LOGIN_NOT_STARTED", "CDP_UNAVAILABLE"):
                raise
    lch = launcher or make_launcher(ctx.home)
    verified = lch.start()
    lch.blank_check(verified)          # 走到这里说明没有进行中的登录，浏览器里不该有任何非空白页

    def body(st):
        with db.write_tx(ctx.conn):
            task_id = runs.add_planned_tasks(ctx.conn, ctx.clock, st.run_id, [("login", {"login": True})])["login"]
        gate.reserve("login", st.run_id)
        transport = make_transport(ctx, verified)
        keep = {"tab": False}
        st.closers.append(lambda: _close_or_detach(ctx, transport, keep["tab"]))
        page = page_mod.LoginPage(transport, monotonic=ctx.clock.monotonic)
        obs = page.open() or page.observe(wait=START_CAPTURE_SEC, known_digest=None, allow_toggle=True, refresh=None)
        st.summary["login"] = {"state": obs.state, "reason": obs.reason, "toggles": obs.toggles}
        if obs.state == "blocked":
            _clear(ctx.home)
            blocked = gate.persist_block(st.run_id, reason_code=obs.reason)   # 冷却先单独提交

            def bookkeep() -> None:
                with db.write_tx(ctx.conn):
                    runs.finish_task(ctx.conn, ctx.clock, task_id, status="blocked", failure_code="RISK_DETECTED",
                                     failure_message=obs.reason)
            network_run.best_effort_write(ctx, bookkeep)
            raise blocked
        if obs.state not in ("qr", "waiting", "logged_in"):
            with db.write_tx(ctx.conn):
                runs.finish_task(ctx.conn, ctx.clock, task_id, status="failed", failure_code="CAPTURE_UNKNOWN",
                                 failure_message=obs.reason)
            raise EnvError("CAPTURE_UNKNOWN", public_message("CAPTURE_UNKNOWN"))
        with db.write_tx(ctx.conn):
            runs.finish_task(ctx.conn, ctx.clock, task_id, status="ok")
        st.completed = 1
        if obs.state == "logged_in":
            _clear(ctx.home)
            return _view("already_logged_in", None, NEXT_DONE, None)
        state = {"target_id": transport.target_id, "run_id": st.run_id, "started_at": iso_utc(ctx.clock.now()),
                 "refreshes": 0, "qr_digest": payload_digest(obs.payload) if obs.state == "qr" else None}
        qr_png = _save_qr(ctx, obs.payload, light_terminal=light_terminal) if obs.state == "qr" else None
        _write_state(ctx.home, state)
        keep["tab"] = True
        if obs.state == "qr":
            return _view("waiting_scan", state, NEXT_SHOW_QR, qr_png,
                         surface="browser", window_raised=page.window_raised)
        if obs.screenshot_failures:
            ctx.warnings.append("专用浏览器截图不可用，未能识别二维码")
        return _view("qr_not_found", state, NEXT_NO_QR, None,
                     surface="browser", window_raised=page.window_raised)

    out = network_run.execute(ctx, gate, actions=1, kind="scan", config={"login": True}, body=body)
    if out.primary is not None:
        raise out.primary
    data = dict(out.data)
    data["budget_remaining_24h"] = gate.ledger.remaining()
    return data, out.run_id

def status(ctx, *, wait: int = DEFAULT_STATUS_WAIT_SEC, launcher=None, show_qr: bool = False,
           light_terminal: bool = False, dark_terminal: bool = False) -> dict:
    require_online_enabled(ctx)
    light_terminal = _light_terminal(ctx, light_terminal, dark_terminal)
    if isinstance(wait, bool) or not isinstance(wait, int) or not 0 <= wait <= MAX_STATUS_WAIT_SEC:
        raise InvalidInput([ErrorItem("SEMANTIC_INVALID", f"--wait 必须是 0 到 {MAX_STATUS_WAIT_SEC} 之间的整数秒", "--wait")])
    from ..adapter import login as page_mod
    from ..adapter.qr import payload_digest
    state = _read_state(ctx.home)
    if state is None:
        raise EnvError("LOGIN_NOT_STARTED", public_message("LOGIN_NOT_STARTED"))
    try:
        verified = (launcher or make_launcher(ctx.home)).verify()
    except EnvError as err:
        if err.code == "CDP_UNAVAILABLE":                 # 浏览器已不在，登录页不可能还在
            _clear(ctx.home)
        raise
    sleep, rng = make_pacing(ctx)
    gate = Gate(ctx, sleep=sleep, rng=rng)
    with gate.hold(0):                                    # 持浏览器锁；冷却中或时钟异常直接退出 3
        try:
            transport = make_attach_transport(ctx, verified, state["target_id"])
        except EnvError as err:
            if err.code == "LOGIN_NOT_STARTED":
                _clear(ctx.home)
            raise
        keep = True
        try:
            if (ctx.clock.now() - parse_iso(state["started_at"])).total_seconds() > SESSION_MAX_SEC:
                keep = False
                _clear(ctx.home)
                raise EnvError("LOGIN_TIMEOUT", public_message("LOGIN_TIMEOUT"))

            def refresh() -> bool:
                if state["refreshes"] >= MAX_REFRESHES:
                    return False
                gate.reserve("login", state["run_id"])
                state["refreshes"] += 1
                _write_state(ctx.home, state)
                return True

            page = page_mod.LoginPage(transport, monotonic=ctx.clock.monotonic)
            if show_qr:                               # 用户说看不到：把窗口重新提到前台，再重画一次
                page.activate()
            obs = page.observe(wait=float(wait), known_digest=state["qr_digest"],
                               allow_toggle=state["qr_digest"] is None, refresh=refresh, report_current=show_qr)
            if obs.state == "logged_in":
                keep = False
                _clear(ctx.home)
                return _view("confirmed", state, NEXT_DONE, None)
            if obs.state == "qr":
                digest = payload_digest(obs.payload)
                changed = digest != state["qr_digest"]
                state["qr_digest"] = digest
                qr_png = _save_qr(ctx, obs.payload, light_terminal=light_terminal)
                _write_state(ctx.home, state)
                if changed:
                    return _view("qr_updated", state, NEXT_QR_UPDATED, qr_png, _login_notes(obs),
                                 surface="browser", window_raised=page.window_raised)
                return _view("waiting_scan", state, NEXT_SHOW_QR, qr_png, _login_notes(obs),
                             surface="browser", window_raised=page.window_raised)
            if obs.state == "waiting":
                if state["qr_digest"] is None:
                    return _view("qr_not_found", state, NEXT_NO_QR, None, _login_notes(obs),
                                 surface="browser", window_raised=page.window_raised)
                return _view("waiting_scan", state, NEXT_WAITING, str(_qr_path(ctx.home)), _login_notes(obs),
                             surface="browser", window_raised=page.window_raised)
            if obs.state == "blocked":
                keep = False
                _clear(ctx.home)
                raise gate.persist_block(state["run_id"], reason_code=obs.reason)
            if obs.state == "expired":
                keep = False
                _clear(ctx.home)
                raise EnvError("LOGIN_TIMEOUT", public_message("LOGIN_TIMEOUT"))
            raise EnvError("CAPTURE_UNKNOWN", public_message("CAPTURE_UNKNOWN"))
        finally:
            _close_or_detach(ctx, transport, keep)

def cancel(ctx, launcher=None) -> dict:
    """任何时候可用（包括在线适配器禁用时）：只关闭本工具记录的登录页，并删除状态与二维码文件。"""
    state = _read_state(ctx.home)
    if state is None:
        _clear(ctx.home)
        return {"login": {"cancelled": False}}
    try:
        verified = (launcher or make_launcher(ctx.home)).verify()
        with BrowserLock(ctx.home):
            transport = make_attach_transport(ctx, verified, state["target_id"])
            _close_or_detach(ctx, transport, keep=False)
    except EnvError as err:
        if err.code not in ("LOGIN_NOT_STARTED", "CDP_UNAVAILABLE"):
            raise
    _clear(ctx.home)
    return {"login": {"cancelled": True}}

def register(sub, set_handler):
    p = sub.add_parser("login", help="扫码登录专用浏览器：start 把二维码画在命令输出里，status 等待确认，cancel 关闭登录页")
    s = p.add_subparsers(dest="login_cmd")
    s.required = True
    tq = s.add_parser("test-qr", help="画一张测试二维码确认显示是否可扫；不联网、不计动作")
    tq.add_argument("--light-terminal", action="store_true", help="按浅色背景终端画字符二维码")
    set_handler(tq, "login test-qr",
                lambda ns, w: with_context(ns, w, lambda ctx: test_qr(ctx, light_terminal=ns.light_terminal)))
    st = s.add_parser("start", help="打开固定登录页，把二维码画在命令输出里并保存为 PNG 后立即返回（受在线门禁与动作额度约束）")
    st.add_argument("--light-terminal", action="store_true", help="按浅色背景终端画字符二维码")
    st.add_argument("--dark-terminal", action="store_true", help="按深色背景终端画字符二维码")
    set_handler(st, "login start",
                lambda ns, w: with_context(ns, w, lambda ctx: start(ctx, light_terminal=ns.light_terminal,
                                                                    dark_terminal=ns.dark_terminal), write=True))
    ss = s.add_parser("status", help="在限定秒数内等待扫码确认；二维码失效时按额度刷新并画出新的")
    ss.add_argument("--wait", type=int, default=DEFAULT_STATUS_WAIT_SEC)
    ss.add_argument("--show-qr", action="store_true", help="重新画出当前二维码")
    ss.add_argument("--light-terminal", action="store_true", help="按浅色背景终端画字符二维码")
    ss.add_argument("--dark-terminal", action="store_true", help="按深色背景终端画字符二维码")
    set_handler(ss, "login status",
                lambda ns, w: with_context(ns, w, lambda ctx: status(ctx, wait=ns.wait, show_qr=ns.show_qr,
                                                                      light_terminal=ns.light_terminal,
                                                                      dark_terminal=ns.dark_terminal), write=True))
    sc = s.add_parser("cancel", help="关闭本工具记录的登录页并删除二维码文件；任何时候可用")
    set_handler(sc, "login cancel", lambda ns, w: with_context(ns, w, lambda ctx: cancel(ctx), write=True))
