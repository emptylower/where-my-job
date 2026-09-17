# tests/unit/test_skill_references.py
import pathlib, re

REFS = pathlib.Path(__file__).resolve().parents[2] / "skill" / "references"
ALL = ["interview.md", "privacy-boundary.md", "profile-schema.md", "strategy-schema.md", "scoring-schema.md",
       "panel-schema.md", "evidence-report-schema.md", "event-schema.md", "stream-schema.md",
       "report-template.md", "research-checklist.md"]

def test_all_eleven_reference_files_exist_and_nonempty():
    for name in ALL:
        p = REFS / name
        assert p.exists(), name
        assert len(p.read_text(encoding="utf-8")) > 300, name

def test_interview_maps_to_real_profile_keys_and_records_defaults():
    t = (REFS / "interview.md").read_text(encoding="utf-8")
    assert "非必答" in t and "campus_policy" in t and "auto" in t
    assert "不会手写代码" in t and "不允许" in t
    for key in ("profile.targets.directions", "profile.targets.cities", "profile.targets.experience_scope",
                "profile.redlines", "scoring.experience_allowlist"):
        assert f"`{key}`" in t, key
    for level in ("familiar", "working", "proficient"):
        assert f"`{level}`" in t, level
    for stale in ("target_roles", "red_lines", "experience_range", "1–5"):
        assert stale not in t, stale

def test_report_template_has_four_fixed_headings_in_order_and_no_percent():
    t = (REFS / "report-template.md").read_text(encoding="utf-8")
    parts = ["## 招聘信号判断", "## JD 翻译", "## 不匹配点", "## 简历建议"]
    idx = [t.index(p) for p in parts]
    assert idx == sorted(idx)
    assert not re.search(r"^## \d", t, re.M)
    for sub in ("### 事实清单", "### 支持信号", "### 反对信号", "### 未知项", "### 定性倾向（推断）",
                "### 已证实经历如何表达", "### 要达标还需补的行动"):
        assert sub in t, sub
    assert "与所选倾向有关的支持线索" in t
    assert "展示持续性" in t and "当前招聘意向" in t
    assert not re.search(r"\d+\s*%", t)
    assert "倾向真实在招" in t and "倾向长期挂岗" in t and "证据不足" in t
    assert "持续可见" not in t

def test_research_checklist_has_can_and_cannot_say_for_each_item():
    text = (REFS / "research-checklist.md").read_text(encoding="utf-8")
    rows = [[part.strip() for part in line.strip().strip("|").split("|")]
            for line in text.splitlines() if line.startswith("|")]
    assert rows[0] == ["项", "怎么查", "可以说", "不可以说"]
    body = [r for r in rows[1:] if not all(set(c) <= {"-", ":", " "} for c in r)]
    assert len(body) >= 5
    assert all(len(r) == 4 and all(r) for r in body)
    assert "未核验" in text

def test_research_checklist_evidence_skeleton_names_schema_version_and_origin_rule():
    t = (REFS / "research-checklist.md").read_text(encoding="utf-8")
    assert "`schema_version`" in t and "常量 1" in t
    assert "--origin" in t and "published_at" in t and "省略" in t

def test_privacy_boundary_lists_what_cli_never_does():
    t = (REFS / "privacy-boundary.md").read_text(encoding="utf-8")
    for phrase in ("不调用", "Cookie", "raw", "resume/", "--local-out"):
        assert phrase in t, phrase
