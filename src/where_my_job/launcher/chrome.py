"""自有受限 Chrome：专用 profile、空白页、只回环、无 --remote-allow-origins；启动/校验/停止全部基于可证明的进程身份。"""
from __future__ import annotations
import json, os, re, time
from dataclasses import dataclass, asdict
from typing import Callable
from urllib.parse import urlsplit
from ..clock import SystemClock, iso_utc
from ..errors import EnvError, WmjError
from ..paths import Layout, atomic_write_text
from ..policy.layout import checked_network_layout
from ..browser_pages import extra_pages, not_blank_error
from ..policy.lock import BrowserLock
from ..public_messages import public_message
from .inspect import Inspector, OwnershipError, ProcIdentity

CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DEFAULT_PORT = 9222
START_TIMEOUT_SEC = 20.0
STOP_TIMEOUT_SEC = 10.0
POLL_SEC = 0.5
LOOPBACK_HOSTS = ("127.0.0.1", "::1")
_WS_PATH = re.compile(r"/devtools/browser/[A-Za-z0-9-]+")

@dataclass(frozen=True)
class BrowserState:
    pid: int
    create_time: float
    exe: str
    profile: str
    port: int
    started_at: str

@dataclass(frozen=True)
class VerifiedBrowser:
    state: BrowserState
    ws_url: str

def _err(code: str) -> EnvError:
    return EnvError(code, public_message(code))

def _host_of(addr: str) -> str:
    host = addr.rsplit(":", 1)[0]
    return host[1:-1] if host.startswith("[") and host.endswith("]") else host

def validate_ws_url(url, port: int) -> str:
    if not isinstance(url, str):
        raise _err("CDP_NOT_LOOPBACK")
    try:
        p = urlsplit(url)
        ok = (p.scheme == "ws" and p.hostname in LOOPBACK_HOSTS and p.port == int(port) and not p.username
              and not p.password and not p.query and not p.fragment and bool(_WS_PATH.fullmatch(p.path)))
    except ValueError:
        ok = False
    if not ok:
        raise _err("CDP_NOT_LOOPBACK")
    return url

class ChromeLauncher:
    def __init__(self, lay: Layout, inspector=None, chrome_path: str = CHROME_PATH, port: int = DEFAULT_PORT,
                 exists: Callable[[str], bool] = os.path.exists, sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic):
        self.lay = checked_network_layout(lay)
        self.inspector = inspector or Inspector()
        self.chrome_path, self.port, self.exists = chrome_path, port, exists
        self.sleep, self.monotonic = sleep, monotonic
        self.profile = self.lay.browser_profile
        self.state_path = self.lay.state / "browser.json"

    def argv(self) -> list[str]:
        return [self.chrome_path, f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}",
                "--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble", "about:blank"]

    # ---- 元数据 ----
    def _write_state(self, st: BrowserState) -> None:
        atomic_write_text(self.state_path, json.dumps(asdict(st)), lay=self.lay)

    def read_state(self) -> BrowserState | None:
        if not self.state_path.exists():
            return None
        try:
            return BrowserState(**json.loads(self.state_path.read_text(encoding="utf-8")))
        except (ValueError, TypeError):
            return None

    def _remove_state(self) -> None:
        try:
            self.state_path.unlink()
        except FileNotFoundError:
            pass

    # ---- 归属 ----
    def _argv_is_ours(self, cmdline: tuple[str, ...]) -> bool:
        profiles = [a for a in cmdline if a.startswith("--user-data-dir=")]
        ports = [a for a in cmdline if a.startswith("--remote-debugging-port=")]
        return (profiles == [f"--user-data-dir={self.profile}"] and ports == [f"--remote-debugging-port={self.port}"]
                and not any(a.startswith("--remote-allow-origins") for a in cmdline))

    def _identity_matches(self, ident: ProcIdentity, st: BrowserState) -> bool:
        return (abs(ident.create_time - st.create_time) < 1e-3
                and os.path.realpath(ident.exe) == os.path.realpath(self.chrome_path)
                and st.profile == str(self.profile) and st.port == self.port
                and self._argv_is_ours(ident.cmdline))

    def _owned(self, st: BrowserState) -> ProcIdentity:
        try:
            ident = self.inspector.identity(st.pid)
        except OwnershipError:
            raise _err("PROFILE_NOT_OWNED") from None
        if not self._identity_matches(ident, st):
            raise _err("PROFILE_NOT_OWNED")
        return ident

    def _check_listeners(self, pid: int) -> None:
        own = self.inspector.listeners_of(pid, self.port)
        if not own:
            raise _err("CDP_UNAVAILABLE")
        on_port = self.inspector.listeners_on(self.port)
        if any(_host_of(a) not in LOOPBACK_HOSTS for a in own) or any(_host_of(a) not in LOOPBACK_HOSTS for _, a in on_port):
            raise _err("CDP_NOT_LOOPBACK")
        if any(p != pid for p, _ in on_port):
            raise _err("PROFILE_NOT_OWNED")

    def verify(self) -> VerifiedBrowser:
        st = self.read_state()
        if st is None or not self.inspector.alive(st.pid):
            raise _err("CDP_UNAVAILABLE")
        self._owned(st)
        self._check_listeners(st.pid)
        version = self.inspector.fetch_version(self.port)
        if version is None:
            raise _err("CDP_UNAVAILABLE")
        return VerifiedBrowser(state=st, ws_url=validate_ws_url(version.get("webSocketDebuggerUrl"), self.port))

    def blank_check(self, verified: VerifiedBrowser, allow_target_id: str | None = None) -> None:
        """开工前确认专用浏览器里只有空白页（另可允许本工具记录的那一个登录页）。
        必须传入已通过归属校验的 VerifiedBrowser：这条铁律写在签名里，避免有人在未校验时读调试端口。
        只读 /json/list，不建立 CDP 会话、不导航、不占动作额度；取不到清单时不拦，由建会话时兜底。"""
        if verified.state.port != self.port:
            raise _err("PROFILE_NOT_OWNED")
        targets = self.inspector.fetch_targets(self.port)
        if targets is None:
            return
        extra = extra_pages(targets, allow_target_id)
        if extra:
            raise not_blank_error(extra)

    # ---- 启动 ----
    def start(self) -> VerifiedBrowser:
        with BrowserLock(self.lay):
            return self._start_locked()

    def _start_locked(self) -> VerifiedBrowser:
        if not self.exists(self.chrome_path):
            raise _err("CDP_UNAVAILABLE")
        if self.inspector.fetch_version(self.port) is not None:
            if self.read_state() is None:
                raise _err("PROFILE_NOT_OWNED")
            return self.verify()
        self.profile.mkdir(parents=True, exist_ok=True)
        os.chmod(self.profile, 0o700)
        pid = self.inspector.popen(self.argv())
        new_state: BrowserState | None = None
        try:
            ident = self.inspector.identity(pid)
            new_state = BrowserState(pid=pid, create_time=ident.create_time, exe=ident.exe, profile=str(self.profile),
                                     port=self.port, started_at=iso_utc(SystemClock().now()))
            if not self._identity_matches(ident, new_state):
                raise _err("PROFILE_NOT_OWNED")
            self._write_state(new_state)
            deadline = self.monotonic() + START_TIMEOUT_SEC
            while self.inspector.fetch_version(self.port) is None:
                if self.monotonic() >= deadline:
                    raise _err("CDP_UNAVAILABLE")
                self.sleep(POLL_SEC)
            return self.verify()
        except OwnershipError:
            self._remove_state()
            raise _err("PROFILE_NOT_OWNED") from None
        except WmjError:
            if new_state is not None:
                self._cleanup_new(new_state)
            raise

    def _cleanup_new(self, st: BrowserState) -> None:
        """只终止本调用新建且仍能证明归属的进程。"""
        try:
            ident = self.inspector.identity(st.pid)
        except OwnershipError:
            self._remove_state()
            return
        if not self._identity_matches(ident, st):
            return
        self.inspector.terminate(st.pid)
        if self._wait_exit(st.pid):
            self._remove_state()

    def _wait_exit(self, pid: int) -> bool:
        deadline = self.monotonic() + STOP_TIMEOUT_SEC
        while self.inspector.alive(pid):
            if self.monotonic() >= deadline:
                return False
            self.sleep(POLL_SEC)
        return True

    # ---- 停止 ----
    def stop(self) -> dict:
        with BrowserLock(self.lay):
            st = self.read_state()
            if st is None:
                return {"stopped": False, "pid": None}
            if not self.inspector.alive(st.pid):
                if any(p == st.pid for p, _ in self.inspector.listeners_on(self.port)):
                    raise _err("CDP_UNAVAILABLE")
                self._remove_state()
                return {"stopped": True, "pid": st.pid, "already_exited": True}
            self._owned(st)
            self.inspector.terminate(st.pid)
            if not self._wait_exit(st.pid):
                self._owned(st)                          # 升级前再次确认身份
                self.inspector.kill(st.pid)
                if not self._wait_exit(st.pid):
                    raise _err("CDP_UNAVAILABLE")
            if any(p == st.pid for p, _ in self.inspector.listeners_on(self.port)):
                raise _err("CDP_UNAVAILABLE")
            self._remove_state()
            return {"stopped": True, "pid": st.pid}
