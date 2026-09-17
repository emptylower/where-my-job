# tests/unit/test_examples_validate.py
import json, pathlib, re
import pytest
from where_my_job.validate import validate, Facts

EX = pathlib.Path(__file__).resolve().parents[2] / "skill" / "examples"
JOB = "boss:SYN0001aaaa"

SIMPLE = {
    "profile.synthetic-qc-to-aipm.json": "profile",
    "strategy.first-page.json": "strategy",
    "strategy.multi-city.json": "strategy",        # 多城多页样板：只有单页样板可抄，agent 就只会抄单页
    "scoring.minimal-aipm.json": "scoring",
    "panel.default.json": "panel",
    "stream.synthetic-interviews.json": "stream",
}

def test_exactly_seven_examples_exist():
    assert sorted(p.name for p in EX.glob("*.json")) == sorted([*SIMPLE, "report.synthetic.json"])

@pytest.mark.parametrize("name,kind", sorted(SIMPLE.items()))
def test_simple_examples_validate(name, kind):
    obj = json.loads((EX / name).read_text(encoding="utf-8"))
    issues = validate(kind, obj, Facts())
    assert issues == [], [(i.path, i.message) for i in issues]

def test_report_example_validates_against_synthetic_facts():
    obj = json.loads((EX / "report.synthetic.json").read_text(encoding="utf-8"))
    facts = Facts(
        job_ids=frozenset({JOB}),
        bundle_ids_by_job={JOB: frozenset({"bundle_SYN0001"})},
        evidence_ids_by_job={JOB: frozenset({"ev_SYN0001detail"})},
    )
    issues = validate("report", obj, facts)
    assert issues == [], [(i.path, i.message) for i in issues]
    assert obj["job_id"] == JOB and obj["authentic"]["conclusion_label"] == "推断"
    assert not re.search(r"\d+\s*%", obj["report_md"])

def test_examples_only_contain_synthetic_ids():
    for p in EX.glob("*.json"):
        text = p.read_text(encoding="utf-8")
        for jid in re.findall(r"boss:([A-Za-z0-9~_-]+)", text):
            assert jid.startswith("SYN"), f"{p.name}: 非合成 ID boss:{jid}"
        assert "securityId" not in text and "security_id" not in text and ".search." not in text

def test_examples_are_referenced_from_skill_md():
    skill = (EX.parents[1] / "SKILL.md").read_text(encoding="utf-8")
    assert "skill/examples/" in skill
