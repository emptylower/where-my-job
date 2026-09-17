import json
import pytest
from where_my_job.errors import Blocked, EnvError
from where_my_job.launcher.chrome import ChromeLauncher, CHROME_PATH, BrowserState, validate_ws_url
from where_my_job.policy.layout import checked_network_layout
from where_my_job.policy.lock import BrowserLock
from tests.helpers.fake_inspector import FakeInspector

class FakeTime:
    def __init__(self): self.t = 0.0
    def monotonic(self): return self.t
    def sleep(self, s): self.t += s

def _launcher(wmj_home, insp, **kw):
    ft = FakeTime()
    return ChromeLauncher(wmj_home, inspector=insp, exists=lambda p: True, sleep=ft.sleep, monotonic=ft.monotonic, **kw)

def _owned_cmd(wmj_home, port=9222, extra=()):
    prof = checked_network_layout(wmj_home).browser_profile
    return [CHROME_PATH, f"--remote-debugging-port={port}", f"--user-data-dir={prof}", "--no-first-run", *extra, "about:blank"]

def _seed_owned(wmj_home, insp, *, cmd=None, listen="127.0.0.1:9222", create_time=1000.0, exe=CHROME_PATH, **proc):
    insp.add_process(4242, create_time=create_time, exe=exe, cmdline=cmd or _owned_cmd(wmj_home), **proc)
    if listen:
        insp.listen.append((4242, listen))
    insp.version = {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/abc-123"}
    l = _launcher(wmj_home, insp)
    l._write_state(BrowserState(pid=4242, create_time=1000.0, exe=CHROME_PATH,
                                profile=str(checked_network_layout(wmj_home).browser_profile), port=9222, started_at="t"))
    return l

def test_start_builds_restricted_blank_argv_and_writes_state(wmj_home):
    insp = FakeInspector()
    v = _launcher(wmj_home, insp).start()
    popen = [c for c in insp.calls if c[0] == "popen"]
    assert insp.calls[0] == ("fetch_version", 9222)                 # 启动前不可达
    argv = list(popen[0][1])
    prof = str(checked_network_layout(wmj_home).browser_profile)
    assert argv[0] == CHROME_PATH and argv[-1] == "about:blank"
    assert [a for a in argv if a.startswith("--user-data-dir=")] == [f"--user-data-dir={prof}"]
    assert [a for a in argv if a.startswith("--remote-debugging-port=")] == ["--remote-debugging-port=9222"]
    assert not any(a.startswith("--remote-allow-origins") for a in argv)
    assert "--restore-last-session" not in argv
    st = json.loads((checked_network_layout(wmj_home).state / "browser.json").read_text())
    assert st["pid"] == 4242 and st["create_time"] == 1000.0 and st["exe"] == CHROME_PATH
    assert v.ws_url == "ws://127.0.0.1:9222/devtools/browser/abc-123"

def test_start_refuses_when_chrome_missing(wmj_home):
    l = ChromeLauncher(wmj_home, inspector=FakeInspector(), exists=lambda p: False)
    with pytest.raises(EnvError) as ei:
        l.start()
    assert ei.value.code == "CDP_UNAVAILABLE"

def test_start_refuses_foreign_browser_already_on_port(wmj_home):
    insp = FakeInspector(); insp.version = {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/x"}
    with pytest.raises(EnvError) as ei:
        _launcher(wmj_home, insp).start()
    assert ei.value.code == "PROFILE_NOT_OWNED" and not [c for c in insp.calls if c[0] == "popen"]

def test_start_never_ready_cleans_only_the_new_owned_pid(wmj_home):
    insp = FakeInspector(behaviour="never_ready")
    with pytest.raises(EnvError) as ei:
        _launcher(wmj_home, insp).start()
    assert ei.value.code == "CDP_UNAVAILABLE" and ("terminate", 4242) in insp.calls
    assert not (checked_network_layout(wmj_home).state / "browser.json").exists()

def test_start_does_not_kill_process_whose_argv_is_not_ours(wmj_home):
    insp = FakeInspector(behaviour="argv_mismatch")
    with pytest.raises(EnvError):
        _launcher(wmj_home, insp).start()
    assert not [c for c in insp.calls if c[0] in ("terminate", "kill")]

@pytest.mark.parametrize("mutate,code", [
    ({"cmd_suffix": "-other"}, "PROFILE_NOT_OWNED"),                   # profile 前缀碰撞
    ({"create_time": 999.0}, "PROFILE_NOT_OWNED"),                     # PID 复用
    ({"exe": "/Applications/Chromium.app/Contents/MacOS/Chromium"}, "PROFILE_NOT_OWNED"),
    ({"dup_profile": True}, "PROFILE_NOT_OWNED"),
    ({"allow_origins": True}, "PROFILE_NOT_OWNED"),
    ({"listen": None}, "CDP_UNAVAILABLE"),                             # 空 lsof
    ({"listen": "*:9222"}, "CDP_NOT_LOOPBACK"),
])
def test_verify_rejections(wmj_home, mutate, code):
    insp = FakeInspector()
    prof = str(checked_network_layout(wmj_home).browser_profile)
    cmd = _owned_cmd(wmj_home)
    if mutate.get("cmd_suffix"):
        cmd = [a + mutate["cmd_suffix"] if a.startswith("--user-data-dir=") else a for a in cmd]
    if mutate.get("dup_profile"):
        cmd.insert(2, f"--user-data-dir={prof}")
    if mutate.get("allow_origins"):
        cmd.insert(1, "--remote-allow-origins=*")
    l = _seed_owned(wmj_home, insp, cmd=cmd, listen=mutate.get("listen", "127.0.0.1:9222"),
                    create_time=mutate.get("create_time", 1000.0), exe=mutate.get("exe", CHROME_PATH))
    with pytest.raises(EnvError) as ei:
        l.verify()
    assert ei.value.code == code

def test_verify_rejects_mixed_foreign_listener(wmj_home):
    insp = FakeInspector()
    l = _seed_owned(wmj_home, insp)
    insp.listen.append((777, "10.0.0.5:9222"))
    with pytest.raises(EnvError) as ei:
        l.verify()
    assert ei.value.code == "CDP_NOT_LOOPBACK"
    insp.listen[-1] = (777, "127.0.0.1:9222")
    with pytest.raises(EnvError) as ei:
        l.verify()
    assert ei.value.code == "PROFILE_NOT_OWNED"

@pytest.mark.parametrize("url", ["ws://10.0.0.5:9222/devtools/browser/x", "ws://127.0.0.1:9333/devtools/browser/x",
                                 "wss://127.0.0.1:9222/devtools/browser/x", "ws://127.0.0.1:9222/devtools/page/x",
                                 "ws://127.0.0.1:9222/devtools/browser/x?y=1", "ws://u:p@127.0.0.1:9222/devtools/browser/x",
                                 "ws://localhost:9222/devtools/browser/x", None])
def test_ws_url_validation(url):
    with pytest.raises(EnvError) as ei:
        validate_ws_url(url, 9222)
    assert ei.value.code == "CDP_NOT_LOOPBACK"
    assert validate_ws_url("ws://[::1]:9222/devtools/browser/abc-1", 9222).startswith("ws://[::1]")

def test_stop_terminates_confirms_exit_and_removes_state(wmj_home):
    insp = FakeInspector(); l = _seed_owned(wmj_home, insp)
    assert l.stop() == {"stopped": True, "pid": 4242}
    assert ("terminate", 4242) in insp.calls and not l.state_path.exists()

def test_stop_escalates_to_kill_only_after_reverify(wmj_home):
    insp = FakeInspector(); l = _seed_owned(wmj_home, insp, ignore_term=True)
    assert l.stop()["stopped"] is True and ("kill", 4242) in insp.calls

def test_stop_unconfirmed_exit_keeps_state(wmj_home):
    insp = FakeInspector(); l = _seed_owned(wmj_home, insp, ignore_term=True, ignore_kill=True)
    with pytest.raises(EnvError) as ei:
        l.stop()
    assert ei.value.code == "CDP_UNAVAILABLE" and l.state_path.exists()

def test_stop_refuses_unowned_process_and_keeps_state(wmj_home):
    insp = FakeInspector(); l = _seed_owned(wmj_home, insp, create_time=555.0)
    with pytest.raises(EnvError) as ei:
        l.stop()
    assert ei.value.code == "PROFILE_NOT_OWNED" and l.state_path.exists()
    assert not [c for c in insp.calls if c[0] in ("terminate", "kill")]

def test_stop_without_state_and_with_already_exited_process(wmj_home):
    insp = FakeInspector()
    assert _launcher(wmj_home, insp).stop() == {"stopped": False, "pid": None}
    l = _seed_owned(wmj_home, insp, alive=False)
    insp.listen.clear()
    assert l.stop() == {"stopped": True, "pid": 4242, "already_exited": True} and not l.state_path.exists()

def test_start_and_stop_share_browser_lock(wmj_home):
    insp = FakeInspector(); l = _seed_owned(wmj_home, insp)
    with BrowserLock(wmj_home):
        with pytest.raises(Blocked) as ei:
            l.stop()
    assert ei.value.code == "RESOURCE_BUSY"
