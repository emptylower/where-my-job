"""进程/监听/HTTP 探测替身。初始 /json/version 不可达；只有模拟启动后才可达。"""
from __future__ import annotations
from where_my_job.launcher.inspect import ProcIdentity, OwnershipError

class FakeInspector:
    def __init__(self, port: int = 9222, behaviour: str = "healthy"):
        self.port, self.behaviour = port, behaviour
        self.procs: dict[int, dict] = {}
        self.listen: list[tuple[int, str]] = []
        self.version: dict | None = None
        self.targets: list[dict] = [{"type": "page", "url": "about:blank", "id": "T0"}]
        self.next_pid = 4242
        self.calls: list[tuple] = []

    def add_process(self, pid: int, *, create_time: float, exe: str, cmdline: list[str], alive: bool = True,
                    ignore_term: bool = False, ignore_kill: bool = False) -> None:
        self.procs[pid] = {"create_time": create_time, "exe": exe, "cmdline": tuple(cmdline), "alive": alive,
                           "ignore_term": ignore_term, "ignore_kill": ignore_kill}

    def popen(self, argv: list[str]) -> int:
        pid = self.next_pid
        self.calls.append(("popen", tuple(argv)))
        cmd = list(argv)
        if self.behaviour == "argv_mismatch":
            cmd = [a if not a.startswith("--user-data-dir=") else a + "-other" for a in cmd]
        self.add_process(pid, create_time=1000.0, exe=argv[0], cmdline=cmd)
        if self.behaviour == "healthy":
            self.listen.append((pid, f"127.0.0.1:{self.port}"))
            self.version = {"Browser": "Chrome/140", "webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/browser/abc-123"}
        return pid

    def identity(self, pid: int) -> ProcIdentity:
        p = self.procs.get(pid)
        if p is None or not p["alive"]:
            raise OwnershipError("no such process")
        return ProcIdentity(pid=pid, create_time=p["create_time"], exe=p["exe"], cmdline=p["cmdline"])

    def alive(self, pid: int) -> bool:
        return bool(self.procs.get(pid, {}).get("alive"))

    def listeners_of(self, pid: int, port: int) -> list[str]:
        return [a for p, a in self.listen if p == pid and a.rsplit(":", 1)[-1] == str(port)]

    def listeners_on(self, port: int) -> list[tuple[int, str]]:
        return [(p, a) for p, a in self.listen if a.rsplit(":", 1)[-1] == str(port)]

    def _exit(self, pid: int) -> None:
        self.procs[pid]["alive"] = False
        self.listen = [(p, a) for p, a in self.listen if p != pid]
        self.version = None

    def terminate(self, pid: int) -> None:
        self.calls.append(("terminate", pid))
        if not self.procs[pid]["ignore_term"]:
            self._exit(pid)

    def kill(self, pid: int) -> None:
        self.calls.append(("kill", pid))
        if not self.procs[pid]["ignore_kill"]:
            self._exit(pid)

    def fetch_version(self, port: int) -> dict | None:
        self.calls.append(("fetch_version", port))
        return self.version

    def fetch_targets(self, port: int) -> list[dict] | None:
        self.calls.append(("fetch_targets", port))
        return None if self.version is None else list(self.targets)
