# tests/unit/test_readme.py
import pathlib, re
REPO = pathlib.Path(__file__).resolve().parents[2]
README = REPO / "README.md"
GETTING_STARTED = REPO / "docs" / "getting-started.md"     # 首次使用两条路径已从 README 移出
RELEASE_GATE = REPO / "docs" / "release-gate.md"           # 发布门槛与状态行已从 README 移出

def test_sections_present():
    t = README.read_text(encoding="utf-8")
    for h in ("## 这是什么", "## 不做什么", "## 安装", "## 法律与隐私", "## 开发"):
        assert h in t, h
    assert "# 首次使用" in GETTING_STARTED.read_text(encoding="utf-8")
    assert "# 在线功能发布门槛" in RELEASE_GATE.read_text(encoding="utf-8")

def test_install_commands_and_path_check():
    t = README.read_text(encoding="utf-8")
    assert "uv tool install" in t and "uv run --project" in t
    assert "where-my-job version" in t and "where-my-job --version" not in t
    assert "uv tool update-shell" in t or "PATH" in t

def test_legal_links_and_unverified_terms():
    t = README.read_text(encoding="utf-8")
    assert "ipc.court.gov.cn/zh-cn/news/view-4440.html" in t
    assert "cac.gov.cn/2021-08/20/c_1631050028355286.htm" in t
    assert "平台条款" in t and "未核验" in t

def test_online_gate_status_line_is_machine_readable():
    t = RELEASE_GATE.read_text(encoding="utf-8")
    m = re.search(r"^在线功能发布门槛状态：(未通过|已通过)（(\d{4}-\d{2}-\d{2})）$", t, re.M)
    assert m, "docs/release-gate.md 必须有一行 `在线功能发布门槛状态：未通过（YYYY-MM-DD）` 或 `已通过（…）`"

def test_path_a_is_the_isolated_synthetic_demo():
    t = GETTING_STARTED.read_text(encoding="utf-8")
    assert 'mktemp -d "${TMPDIR:-/tmp}/wmj-demo.XXXXXX"' in t
    assert "legacy/*.json" not in t and "broken.json" not in t
    assert "cp ~/where-my-job/skill/examples" not in t

def test_browser_stop_documented_as_always_available():
    gate = RELEASE_GATE.read_text(encoding="utf-8")
    assert "browser stop" in gate and "不受" in gate
