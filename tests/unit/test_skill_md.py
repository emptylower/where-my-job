# tests/unit/test_skill_md.py
import argparse, pathlib, re, shlex
from where_my_job.cli.main import build_parser

REPO = pathlib.Path(__file__).resolve().parents[2]
SKILL = REPO / "SKILL.md"

def _frontmatter(text: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md 必须以 YAML frontmatter 开头"
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip()
    return out

def test_frontmatter_has_name_and_description():
    fm = _frontmatter(SKILL.read_text(encoding="utf-8"))
    assert fm["name"] == "where-my-job"
    assert len(fm["description"]) > 40 and "BOSS" in fm["description"]

def test_five_rules_and_five_scenarios_present():
    text = SKILL.read_text(encoding="utf-8")
    for heading in ("## 铁律 1", "## 铁律 2", "## 铁律 3", "## 铁律 4", "## 铁律 5"):
        assert heading in text, heading
    for scenario in ("首次使用", "日常扫描", "点名深挖", "记录事件", "新建本子"):
        assert f"### 场景：{scenario}" in text, scenario

def _resolve_invocation(parser, invocation: str):
    """按子解析器逐级解析；首个参数以 '-' 开头（纯选项调用，如 --help）时返回 None 表示跳过。"""
    tokens = shlex.split(invocation)[1:]
    tokens = ["profile" if t == "<kind>" else
              "synthetic.json" if t in {"<file>", "F"} else t
              for t in tokens]
    if tokens == ["..."] or (tokens and tokens[0].startswith("-")):
        return None
    current = parser
    position = 0
    while True:
        actions = [a for a in current._actions
                   if isinstance(a, argparse._SubParsersAction)]
        if not actions:
            break
        assert position < len(tokens), invocation
        name = tokens[position]
        assert name in actions[0].choices, invocation
        current = actions[0].choices[name]
        position += 1
    assert current is not parser, invocation
    return current

def test_every_backticked_cli_invocation_exists_in_parser():
    text = SKILL.read_text(encoding="utf-8")
    parser = build_parser()
    invocations = re.findall(r"`(where-my-job\s+[^`\n]+)`", text)
    assert invocations
    for invocation in invocations:
        _resolve_invocation(parser, invocation)
    assert "where-my-job --version" not in text, "SKILL.md 用子命令 `where-my-job version`，不用 --version 选项"

def test_option_only_invocation_is_skipped_and_version_subcommand_resolves():
    parser = build_parser()
    assert _resolve_invocation(parser, "where-my-job --help") is None
    assert _resolve_invocation(parser, "where-my-job --version") is None
    assert _resolve_invocation(parser, "where-my-job version") is not None

def test_no_percent_confidence_promises_and_no_auto_apply():
    text = SKILL.read_text(encoding="utf-8")
    assert "自动投递" in text and "永不" in text
    assert not re.search(r"真招概率|\d+%\s*(置信|可信)", text)

def test_install_location_only_promises_claude_code():
    text = SKILL.read_text(encoding="utf-8")
    assert "~/.claude/skills/where-my-job" in text
    assert "任意 agent 自动发现" not in text

def test_skill_never_mentions_frozen_legacy_input():
    text = SKILL.read_text(encoding="utf-8")
    for word in ("input_selection", "legacy_input", "legacy-20260914"):
        assert word not in text, word

def test_event_scenario_uses_returned_application_id():
    text = SKILL.read_text(encoding="utf-8")
    section = text.split("### 场景：记录事件", 1)[1].split("### 场景：", 1)[0]
    assert "application_id" in section and "stream_revision" in section
    assert "--subject JOB_ID" not in section

def test_demo_uses_isolated_home_and_only_valid_fixtures():
    text = SKILL.read_text(encoding="utf-8")
    assert 'mktemp -d "${TMPDIR:-/tmp}/wmj-demo.XXXXXX"' in text
    assert "broken.json" not in text and "legacy/*.json" not in text
    assert "合肥_AI产品经理.json" in text and "合肥_产品经理.json" in text
