# tests/unit/test_skill_wording.py
import json, pathlib, re

REPO = pathlib.Path(__file__).resolve().parents[2]
SKILL = REPO / "SKILL.md"
REFS = REPO / "skill" / "references"
EX = REPO / "skill" / "examples"
UNVERIFIED = ("多数不考手写代码", "小团队更看作品", "大概率考硬编码", "持续可见")
FROZEN = ("input_selection", "legacy_input", "legacy-20260914")

def _public_files():
    yield SKILL
    yield from sorted(REFS.glob("*.md"))
    yield from sorted(EX.glob("*.json"))

def test_no_unverified_claims_in_skill_references_or_examples():
    for path in _public_files():
        text = path.read_text(encoding="utf-8")
        for phrase in UNVERIFIED:
            assert phrase not in text, (path.name, phrase)

def test_examples_never_use_frozen_legacy_input():
    for path in [SKILL, *sorted(EX.glob("*.json"))]:
        text = path.read_text(encoding="utf-8")
        for word in FROZEN:
            assert word not in text, (path.name, word)

def test_scoring_example_reasons_are_preferences_or_pending_checks():
    scoring = json.loads((EX / "scoring.minimal-aipm.json").read_text(encoding="utf-8"))
    reasons = [d["base_reason"] for d in scoring["score"].values()]
    reasons += [r["reason"] for d in scoring["score"].values() for r in d.get("rules", [])]
    reasons += [r["reason"] for r in scoring.get("exclude", []) + scoring.get("global", [])]
    assert reasons and all(r.strip() for r in reasons)
    for reason in reasons:
        assert not re.search(r"大概率|一定|必然|多数", reason), reason

def test_report_example_is_insufficient_evidence_with_fixed_headings():
    report = json.loads((EX / "report.synthetic.json").read_text(encoding="utf-8"))
    authentic = report["authentic"]
    assert authentic["supporting"] == [] and authentic["opposing"] == []
    assert authentic["conclusion"] == "证据不足" and authentic["conclusion_label"] == "推断"
    assert authentic["unknowns"]
    for heading in ("## 招聘信号判断", "## JD 翻译", "## 不匹配点", "## 简历建议"):
        assert heading in report["report_md"], heading
    assert not re.search(r"^## \d", report["report_md"], re.M)

def test_no_percent_in_skill_template_or_report_example():
    for path in (SKILL, REFS / "report-template.md", EX / "report.synthetic.json"):
        assert not re.search(r"\d+\s*%", path.read_text(encoding="utf-8")), path.name
