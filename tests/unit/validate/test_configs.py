# tests/unit/validate/test_configs.py
import copy
from where_my_job.validate import validate
from tests.conftest import load_fixture

def test_scoring_fixture_valid_and_bad_cases():
    ok = load_fixture("scoring.minimal.json")
    assert validate("scoring", ok) == []
    bad = copy.deepcopy(ok); bad["campus_policy"] = "maybe"
    assert validate("scoring", bad)[0].path == "$.campus_policy"
    bad = copy.deepcopy(ok); bad["classify"] = [{"dir": "X", "when": {"field": "nope", "eq": 1}}]
    issues = validate("scoring", bad)
    assert issues[0].code == "SEMANTIC_INVALID" and issues[0].path == "$.classify[0].when.field"
    bad = copy.deepcopy(ok); bad["experience_allowlist"] = ["2年"]
    assert validate("scoring", bad)[0].path == "$.experience_allowlist[0]"
    bad = copy.deepcopy(ok); del bad["score"]["AI全栈"]["base_reason"]
    assert validate("scoring", bad)[0].code == "SCHEMA_INVALID"

def test_scoring_input_selection_pairing():
    ok = load_fixture("scoring.minimal.json")
    files = [{"name": "合肥_A.json", "sha256": "a" * 64}]
    bad = copy.deepcopy(ok); bad["input_selection"] = "legacy-20260914"
    assert validate("scoring", bad)[0].path == "$.legacy_input"
    bad = copy.deepcopy(ok); bad["legacy_input"] = {"files": files}
    assert validate("scoring", bad)[0].path == "$.legacy_input"
    good = copy.deepcopy(ok); good["input_selection"] = "legacy-20260914"; good["legacy_input"] = {"files": files}
    assert validate("scoring", good) == []
    dup = copy.deepcopy(good); dup["legacy_input"]["files"] = files + [{"name": "合肥_B.json", "sha256": "a" * 64}]
    assert validate("scoring", dup)[0].path == "$.legacy_input.files[1].sha256"
    badname = copy.deepcopy(good); badname["legacy_input"]["files"] = [{"name": "dir/合肥_A.json", "sha256": "a" * 64}]
    assert validate("scoring", badname)[0].code == "SCHEMA_INVALID"

def test_strategy_fixture_valid_and_budget_rules():
    ok = load_fixture("strategy.first-page.json")
    assert validate("strategy", ok) == []
    bad = copy.deepcopy(ok); bad["budget"] = {"max_pages_per_run": 1, "pause_between_actions_sec": [5, 22]}
    assert validate("strategy", bad)[0].path == "$.budget.pause_between_actions_sec[0]"
    big = copy.deepcopy(ok)
    big["searches"] = [{"keywords": [f"k{i}" for i in range(7)], "cities": ["合肥", "上海", "北京", "深圳", "广州", "杭州"], "pages": 2}]
    big["budget"] = {"max_pages_per_run": 80, "pause_between_actions_sec": [12, 22]}
    issues = validate("strategy", big)
    assert issues and issues[0].path == "$.searches" and "80" in issues[0].message
    bad = copy.deepcopy(ok); bad["searches"] = [{"keywords": ["a"], "cities": ["合肥"], "boss_filters": {"experience": "999"}}]
    assert validate("strategy", bad)[0].path == "$.searches[0].boss_filters.experience"
    nobudgetcap = copy.deepcopy(ok); nobudgetcap["budget"] = {"pause_between_actions_sec": [12, 22]}
    assert validate("strategy", nobudgetcap) == []
    numeric = copy.deepcopy(ok); numeric["searches"][0]["boss_filters"] = {"salary": 405}
    assert validate("strategy", numeric)[0].code == "SCHEMA_INVALID"
    arr = copy.deepcopy(ok); arr["searches"][0]["boss_filters"] = {"experience": ["3-5年", "105"]}
    assert validate("strategy", arr) == []
    toomany = copy.deepcopy(ok); toomany["searches"][0]["pages"] = 81
    assert validate("strategy", toomany)[0].code == "SCHEMA_INVALID"

def test_profile_and_panel_fixtures_valid():
    assert validate("profile", load_fixture("profile.synthetic.json")) == []
    assert validate("panel", load_fixture("panel.default.json")) == []
    bad = load_fixture("panel.default.json"); bad["columns"] = ["raw_json"]
    assert validate("panel", bad)[0].path == "$.columns[0]"
    bad = load_fixture("panel.default.json"); bad["charts"] = [{"type": "pie", "by": "dir"}]
    assert validate("panel", bad)[0].path.startswith("$.charts[0]")
    bad = load_fixture("panel.default.json"); bad["sql"] = "select 1"
    assert validate("panel", bad)[0].code == "UNKNOWN_FIELD"
    bad = load_fixture("panel.default.json"); bad["page_size"] = 501
    assert validate("panel", bad)[0].code == "SCHEMA_INVALID"
    tl = load_fixture("panel.default.json"); tl["timeline"] = {"enabled": True, "streams": ["applications", "custom.interviews"]}
    assert validate("panel", tl) == []
    tl["timeline"]["streams"] = ["events; drop"]
    assert validate("panel", tl)[0].code == "SCHEMA_INVALID"
