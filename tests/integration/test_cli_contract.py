# tests/integration/test_cli_contract.py
import json, os, pathlib, subprocess, threading
from tests.conftest import FIXTURES

REPO = pathlib.Path(__file__).resolve().parents[2]

def _run(args, *, cwd, env):
    return subprocess.run(["uv", "run", "--project", str(REPO), "where-my-job", *args],
                          cwd=str(cwd), env=env, capture_output=True, text=True)

def test_runs_from_any_cwd_with_single_line_stdout(tmp_path, wmj_home):
    env = dict(os.environ, WMJ_HOME=str(wmj_home.root))
    r = _run(["status"], cwd=tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    out = r.stdout.strip().splitlines()
    assert len(out) == 1 and json.loads(out[0])["command"] == "status"

def test_exit_codes_cover_0_1_2(tmp_path, wmj_home):
    env = dict(os.environ, WMJ_HOME=str(wmj_home.root))
    assert _run(["status"], cwd=tmp_path, env=env).returncode == 0
    assert _run(["job", "list", "--filter", "raw_json=1"], cwd=tmp_path, env=env).returncode == 1
    bad = dict(env, WMJ_HOME=str(REPO / "src"))
    r = _run(["status"], cwd=tmp_path, env=bad)
    assert r.returncode == 2 and json.loads(r.stdout)["errors"][0]["code"] == "PERMISSION_DENIED"

def test_concurrent_imports_on_fresh_home_do_not_corrupt(tmp_path):
    home = tmp_path / "fresh-home"
    env = dict(os.environ, WMJ_HOME=str(home))
    f = str(FIXTURES / "legacy" / "合肥_AI产品经理.json")
    results = []
    def go():
        results.append(_run(["import", f], cwd=tmp_path, env=env))
    threads = [threading.Thread(target=go) for _ in range(3)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
    envelopes = [json.loads(r.stdout) for r in results]
    assert sum(e["data"]["observations_inserted"] for e in envelopes) == 3
    assert len({e["run_id"] for e in envelopes}) == 3
    assert list((home / "state" / "runs").glob("*.lock")) == []
