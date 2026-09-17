# tests/integration/test_demo_path.py
"""按 README / SKILL.md 的合成 demo 命令顺序经真实 CLI 执行，验证数量、幂等与面板标题。"""
import shutil
from tests.conftest import FIXTURES

REPO = FIXTURES.parents[2]
EX = REPO / "skill" / "examples"
L = FIXTURES / "legacy"

def test_demo_path_a(cli, wmj_home):
    rc, env, _ = cli(["init"])
    assert rc == 0, env
    for kind, name in (("profile", "profile.synthetic-qc-to-aipm.json"),
                       ("scoring", "scoring.minimal-aipm.json"),
                       ("panel", "panel.default.json")):
        rc, env, _ = cli(["validate", kind, str(EX / name)])
        assert rc == 0, env
    for target, name in (("profile.json", "profile.synthetic-qc-to-aipm.json"),
                         ("scoring.json", "scoring.minimal-aipm.json"),
                         ("panel.json", "panel.default.json")):
        dest = wmj_home.config(target)
        shutil.copyfile(EX / name, dest)
        dest.chmod(0o600)
    files = [str(L / "合肥_AI产品经理.json"), str(L / "合肥_产品经理.json")]
    rc, env, _ = cli(["import", *files])
    assert rc == 0, env
    assert env["data"]["observations_inserted"] == 5 and env["data"]["jobs_total"] == 4
    rc, env, _ = cli(["import", *files])
    assert rc == 0, env
    assert env["data"]["observations_inserted"] == 0 and env["data"]["jobs_total"] == 4
    rc, env, _ = cli(["match"])
    assert rc == 0, env
    rc, env, _ = cli(["panel"])
    assert rc == 0, env
    html = wmj_home.panel_latest.read_text(encoding="utf-8")
    assert "合成数据演示" in html
