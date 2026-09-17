# tests/integration/test_match_cmd.py
import json, shutil, time
import pytest
from tests.conftest import FIXTURES
from where_my_job.store import db
L = FIXTURES / "legacy"

def _prep(cli, wmj_home):
    cli(["import", str(L / "合肥_AI产品经理.json"), str(L / "合肥_产品经理.json")])
    shutil.copy(FIXTURES / "scoring.minimal.json", wmj_home.config("scoring.json"))
    shutil.copy(FIXTURES / "profile.synthetic.json", wmj_home.config("profile.json"))

def _count_results(wmj_home, run_id):
    c = db.open_db(wmj_home.db_path)
    try:
        return c.execute("select count(*) from match_results where match_run_id=?", (run_id,)).fetchone()[0]
    finally:
        c.close()

def test_match_default_scoring_and_summary(cli, wmj_home):
    _prep(cli, wmj_home)
    rc, env, _ = cli(["match"])
    assert rc == 0, env
    d = env["data"]
    assert d["jobs_evaluated"] == 4 and d["classified"] >= 1 and d["as_of"] == "2026-09-14T12:00:00.000000Z"
    assert d["campus"] == {"value": "include", "basis": "union_contains_no_experience"}
    assert d["by_dir"]["AI产品经理"] >= 1 and d["by_tier"] and d["input_selection"] == "latest"
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa"])
    j = env["data"]["job"]
    assert j["match_state"] == "current" and j["dir"] == "AI产品经理" and j["tier"] in ("S", "A", "B", "C", "D")
    assert json.loads(j["reasons_json"])[0]["rule_id"] == "base"

def test_reason_deltas_sum_to_score(cli, wmj_home):
    _prep(cli, wmj_home)
    cli(["match"])
    rc, env, _ = cli(["job", "list", "--page-size", "500"])
    scored = [r for r in env["data"]["jobs"] if r["score"] is not None]
    assert scored and all(sum(x["delta"] for x in json.loads(r["reasons_json"])) == r["score"] for r in scored)

def test_match_explicit_as_of_and_campus_exclude(cli, wmj_home):
    _prep(cli, wmj_home)
    sc = json.loads(wmj_home.config("scoring.json").read_text()); sc["campus_policy"] = "exclude"
    wmj_home.config("scoring.json").write_text(json.dumps(sc, ensure_ascii=False))
    rc, env, _ = cli(["match", "--as-of", "2026-09-10T00:00:00Z"])
    assert rc == 0 and env["data"]["as_of"] == "2026-09-10T00:00:00.000000Z" and env["data"]["campus"]["basis"] == "explicit"
    rc, env, _ = cli(["job", "show", "boss:SYN0002bbbb"])   # 在校/应届 岗位
    j = env["data"]["job"]
    assert j["excluded"] == 1 and any(r["rule_id"] == "campus-policy" for r in json.loads(j["exclusion_reasons_json"]))

@pytest.mark.parametrize("experience", ["104", "3-5年", ["3-5年", "104"]])
def test_match_with_strategy_codes_only_year_bands(cli, wmj_home, experience):
    _prep(cli, wmj_home)
    strat = json.loads((FIXTURES / "strategy.first-page.json").read_text())
    strat["searches"][0]["boss_filters"] = {"experience": experience}
    strat["budget"]["max_pages_per_run"] = 20   # 数组筛选展开为 2 个任务；fixture 本身保持 1（Skill demo 依赖）
    sc = json.loads(wmj_home.config("scoring.json").read_text()); sc["exclude"] = []   # 去掉 scoring 侧经验规则
    wmj_home.config("scoring.json").write_text(json.dumps(sc, ensure_ascii=False))
    p = wmj_home.strategies / "s.json"; p.write_text(json.dumps(strat, ensure_ascii=False))
    rc, env, _ = cli(["match", "--strategy", str(p)])
    assert rc == 0, env
    assert env["data"]["campus"] == {"value": "exclude", "basis": "only_year_bands"}

def test_match_with_strategy_no_experience_code_includes(cli, wmj_home):
    _prep(cli, wmj_home)
    strat = json.loads((FIXTURES / "strategy.first-page.json").read_text())
    strat["searches"][0]["boss_filters"] = {"experience": ["经验不限", "104"]}
    strat["budget"]["max_pages_per_run"] = 20   # 两个经验码展开为 2 个任务
    sc = json.loads(wmj_home.config("scoring.json").read_text()); sc["exclude"] = []
    wmj_home.config("scoring.json").write_text(json.dumps(sc, ensure_ascii=False))
    p = wmj_home.strategies / "s.json"; p.write_text(json.dumps(strat, ensure_ascii=False))
    rc, env, _ = cli(["match", "--strategy", str(p)])
    assert rc == 0 and env["data"]["campus"] == {"value": "include", "basis": "union_contains_no_experience"}

def test_match_invalid_scoring_keeps_previous(cli, wmj_home):
    _prep(cli, wmj_home)
    cli(["match"])
    rc0, env0, _ = cli(["status"]); prev = env0["data"]["match"]["current_run_id"]
    wmj_home.config("scoring.json").write_text('{"schema_version": 2}')
    rc, env, _ = cli(["match"])
    assert rc == 1 and env["errors"][0]["code"] in ("SCHEMA_INVALID", "SEMANTIC_INVALID")
    rc, env, _ = cli(["status"])
    assert env["data"]["match"]["current_run_id"] == prev

def test_scoring_changed_warning_on_job_list(cli, wmj_home):
    _prep(cli, wmj_home)
    cli(["match"])
    sc = json.loads(wmj_home.config("scoring.json").read_text()); sc["global"] = []
    wmj_home.config("scoring.json").write_text(json.dumps(sc, ensure_ascii=False))
    rc, env, _ = cli(["job", "list"])
    assert rc == 0 and any("scoring" in w and "过期" in w for w in env["warnings"])

def test_timeout_keeps_previous_batch(cli, wmj_home, tmp_path, monkeypatch):
    _prep(cli, wmj_home)
    rec = json.loads((L / "合肥_AI产品经理.json").read_text(encoding="utf-8"))["jobs"][0]
    rec = dict(rec, title="a" * 18000 + "!", encrypt_job_id="SYN0099aaaa",
               job_link="https://www.zhipin.com/job_detail/SYN0099aaaa.html", job_id="0000000000000099")
    p = tmp_path / "合肥_长标题.json"
    p.write_text(json.dumps({"keyword": "k", "city": "合肥", "filters": {}, "filter_desc": [],
                             "scraped_at": "2026-09-14T11:30:00", "total": 1, "jobs": [rec]}, ensure_ascii=False), encoding="utf-8")
    assert cli(["import", str(p)])[0] == 0
    rc, env, _ = cli(["match"]); assert rc == 0, env
    prev = env["run_id"]; before = _count_results(wmj_home, prev)
    sc = json.loads(wmj_home.config("scoring.json").read_text(encoding="utf-8"))
    sc["classify"][0]["when"] = {"field": "title", "match": "(a+)+$"}
    wmj_home.config("scoring.json").write_text(json.dumps(sc, ensure_ascii=False), encoding="utf-8")
    from where_my_job.rules import limits
    monkeypatch.setattr(limits, "EVAL_TIMEOUT_SEC", 0.5)
    started = time.monotonic()
    rc, env, _ = cli(["match"])
    assert rc == 1 and env["errors"][0]["code"] == "SEMANTIC_INVALID" and time.monotonic() - started < 5
    rc, env, _ = cli(["status"])
    assert env["data"]["match"]["current_run_id"] == prev and _count_results(wmj_home, prev) == before

def test_worker_error_maps_to_internal_exit_2(cli, wmj_home, monkeypatch):
    _prep(cli, wmj_home)
    from where_my_job.service import match as match_service
    from where_my_job.rules.runner import EvalWorkerError
    def boom(*a, **k):
        raise EvalWorkerError("规则进程未返回完整结果")
    monkeypatch.setattr(match_service, "evaluate_batch", boom)
    rc, env, _ = cli(["match"])
    assert rc == 2 and env["errors"][0]["code"] == "INTERNAL"
