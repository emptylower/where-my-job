"""进程、监听与 /json/version 探测的唯一真实实现。psutil 只在本包使用。"""
from __future__ import annotations
import json, os, signal, subprocess, urllib.error, urllib.request
from dataclasses import dataclass
import psutil

@dataclass(frozen=True)
class ProcIdentity:
    pid: int
    create_time: float
    exe: str
    cmdline: tuple[str, ...]

class OwnershipError(Exception):
    """无法取得或确认进程身份（不存在、无权限、僵尸）。"""

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def _parse_lsof(out: str) -> list[tuple[int, str]]:
    pairs, pid = [], None
    for line in out.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            pid = int(line[1:])
        elif line.startswith("n") and pid is not None:
            pairs.append((pid, line[1:]))
    return pairs

class Inspector:
    def identity(self, pid: int) -> ProcIdentity:
        try:
            p = psutil.Process(pid)
            if p.status() == psutil.STATUS_ZOMBIE:
                raise OwnershipError("zombie")
            return ProcIdentity(pid=pid, create_time=p.create_time(), exe=p.exe(), cmdline=tuple(p.cmdline()))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as exc:
            raise OwnershipError(type(exc).__name__) from None

    def alive(self, pid: int) -> bool:
        try:
            return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return False

    def _lsof(self, args: list[str]) -> list[tuple[int, str]]:
        r = subprocess.run(["lsof", "-nP", *args, "-sTCP:LISTEN", "-F", "pn"], capture_output=True, text=True, timeout=10)
        return _parse_lsof(r.stdout)

    def listeners_of(self, pid: int, port: int) -> list[str]:
        return [a for p, a in self._lsof(["-a", "-p", str(pid), "-iTCP"]) if p == pid and a.rsplit(":", 1)[-1] == str(port)]

    def listeners_on(self, port: int) -> list[tuple[int, str]]:
        return self._lsof([f"-iTCP:{port}"])

    def popen(self, argv: list[str]) -> int:
        return subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True).pid

    def terminate(self, pid: int) -> None:
        try: os.kill(pid, signal.SIGTERM)
        except ProcessLookupError: pass

    def kill(self, pid: int) -> None:
        try: os.kill(pid, signal.SIGKILL)
        except ProcessLookupError: pass

    def fetch_version(self, port: int) -> dict | None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(f"http://127.0.0.1:{int(port)}/json/version", timeout=2) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read(65536).decode("utf-8"))
                return data if isinstance(data, dict) else None
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def fetch_targets(self, port: int) -> list[dict] | None:
        """读 /json/list：只用于开工前确认专用浏览器里没有别的标签页。
        不建立 CDP 会话、不导航、不改动任何标签页。"""
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(f"http://127.0.0.1:{int(port)}/json/list", timeout=2) as resp:
                if resp.status != 200:
                    return None
                data = json.loads(resp.read(1 << 20).decode("utf-8"))
                return [t for t in data if isinstance(t, dict)] if isinstance(data, list) else None
        except (urllib.error.URLError, OSError, ValueError):
            return None
