# tests/unit/test_acceptance_docs.py
import pathlib, re, subprocess

REPO = pathlib.Path(__file__).resolve().parents[2]
DOCS = REPO / "docs" / "acceptance"
SCRIPTS = REPO / "scripts"
DEMO = re.compile(r"```bash\n(set -e\nWMJ_DEMO_REPO=.*?)\n```", re.S)

def test_template_has_two_paths_and_gate_table():
    t = (DOCS / "TEMPLATE-beta-acceptance.md").read_text(encoding="utf-8")
    for h in ("## 路径 A", "## 路径 B", "## 非作者试用", "## 联网门槛核对", "## 结论"):
        assert h in t, h
    assert "≤ 30 分钟" in t and "登录耗时" in t and "禁用在线适配器" in t
    assert t.count("| 步骤 |") >= 2
    assert "合成数据演示" in t and "legacy/*.json" not in t
    assert "Document 拦截" in t

def test_brief_lists_materials_and_pass_criteria():
    t = (DOCS / "codex-acceptance-brief.md").read_text(encoding="utf-8")
    for h in ("## 交付材料", "## 通过标准", "## 不通过即阻塞", "## 验收方不做"):
        assert h in t, h
    assert "release_check.py" in t and "tests/regression" in t and "1260" in t
    assert "合成数据演示" in t and "browser stop" in t

def test_demo_block_identical_in_skill_getting_started_and_template():
    blocks = []
    for path in (REPO / "SKILL.md", REPO / "docs" / "getting-started.md", DOCS / "TEMPLATE-beta-acceptance.md"):
        found = DEMO.findall(path.read_text(encoding="utf-8"))
        assert len(found) == 1, path.name
        blocks.append(found[0])
    assert blocks[0] == blocks[1] == blocks[2]
    assert 'mktemp -d "${TMPDIR:-/tmp}/wmj-demo.XXXXXX"' in blocks[0]

def test_timer_script_is_executable_and_prints_elapsed():
    s = SCRIPTS / "acceptance_timer.sh"
    assert s.exists() and s.stat().st_mode & 0o111
    r = subprocess.run(["bash", str(s), "echo", "hi"], capture_output=True, text=True)
    assert r.returncode == 0 and re.search(r"elapsed_seconds=\d+", r.stdout)
