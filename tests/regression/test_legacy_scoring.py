# tests/regression/test_legacy_scoring.py
import json, pathlib
from collections import Counter
import pytest
from tests.regression.legacy_runner import (load_legacy_jobs, run_funnel, parse_tags, classify, score_job, tier,
                                            EXP_KEEP_LEGACY, EXP_KEEP_HANDOFF)
from tests.regression.scoring_presets import frozen_scoring
from where_my_job.config.loader import validate_object

@pytest.fixture
def imported(cli, private_manifest, wmj_home):
    rc, env, _ = cli(["import", "--manifest", private_manifest]); assert rc == 0, env
    from where_my_job.store import db
    c = db.open_db(wmj_home.db_path)
    yield c
    c.close()

def test_legacy_funnel_and_scores(imported):
    f = run_funnel(load_legacy_jobs(imported), EXP_KEEP_LEGACY)
    assert (f.raw, f.matched, f.after_degree, f.final) == (1225, 913, 842, 402)
    assert f.tiers == {"S": 3, "A": 41, "B": 77, "C": 119, "D": 162} and f.total_score == 19726

def test_handoff_intent_adds_exactly_76(imported):
    jobs = load_legacy_jobs(imported)
    a = run_funnel(jobs, EXP_KEEP_LEGACY); b = run_funnel(jobs, EXP_KEEP_HANDOFF)
    assert b.final == 478 and len(b.final_ids - a.final_ids) == 76 and a.final_ids <= b.final_ids
    assert b.tiers == {"S": 4, "A": 47, "B": 95, "C": 143, "D": 189} and b.total_score == 23484

def _all_rows(cli):
    rows, page = [], 1
    while True:
        rc, env, _ = cli(["job", "list", "--page-size", "500", "--page", str(page)]); assert rc == 0, env
        rows += env["data"]["jobs"]
        if not env["data"]["truncated"]:
            return rows
        page += 1

def _expectations(jobs, exp_keep):
    out, seen = {}, set()
    for j in jobs:
        legacy_id = j.get("job_id")
        if not legacy_id or legacy_id in seen:
            continue
        seen.add(legacy_id)
        exp, deg = parse_tags(j.get("tags") or "")
        d = classify(j)
        s = score_job(dict(j, _exp=exp, _deg=deg, _dir=d)) if d else None
        excluded = deg in ("硕士", "博士", "研究生") or exp not in exp_keep
        out["boss:" + str(j.get("encrypt_job_id") or "").strip()] = {
            "dir": d, "excluded": excluded, "rule_score": s, "tier": tier(s) if s is not None else None}
    return out

def _run_frozen(cli, wmj_home, private_manifest, tmp_path, include_campus):
    manifest = json.loads(pathlib.Path(private_manifest).read_text(encoding="utf-8"))
    cfg = frozen_scoring(manifest, include_campus)
    validate_object("scoring", cfg)
    scoring_path = tmp_path / f"{'handoff-intent-v1' if include_campus else 'legacy-20260914'}.scoring.json"
    scoring_path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    wmj_home.config("profile.json").write_text(json.dumps(
        {"schema_version": 1, "profile_revision": "legacy-20260914", "summary": "冻结历史回归用画像占位"}, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["match", "--scoring", str(scoring_path)]); assert rc == 0, env
    assert env["data"]["input_selection"] == "legacy-20260914" and env["data"]["jobs_evaluated"] == 1225
    return {r["job_id"]: r for r in _all_rows(cli)}

@pytest.mark.parametrize("include_campus, final, tiers, total", [
    (False, 402, {"S": 3, "A": 41, "B": 77, "C": 119, "D": 162}, 19726),
    (True, 478, {"S": 4, "A": 47, "B": 95, "C": 143, "D": 189}, 23484),
])
def test_product_engine_frozen_replay_matches_runner_per_job(cli, wmj_home, imported, private_manifest, tmp_path,
                                                              include_campus, final, tiers, total):
    rows = _run_frozen(cli, wmj_home, private_manifest, tmp_path, include_campus)
    expected = _expectations(load_legacy_jobs(imported), EXP_KEEP_HANDOFF if include_campus else EXP_KEEP_LEGACY)
    assert len(expected) == 1225 and set(expected) <= set(rows)
    mismatches = []
    for job_id, e in expected.items():
        r = rows[job_id]
        got = {"dir": r["dir"], "excluded": bool(r["excluded"]), "rule_score": r["rule_score"],
               "tier": r["tier"] if r["dir"] else None}
        if got != e:
            mismatches.append((job_id, e, got))
        if r["rule_score"] is not None:
            assert sum(x["delta"] for x in json.loads(r["reasons_json"])) == r["score"], job_id
    assert mismatches == []
    kept = [r for r in rows.values() if r["dir"] and not r["excluded"]]
    assert len(kept) == final
    assert dict(Counter(r["tier"] for r in kept)) == tiers and sum(r["rule_score"] for r in kept) == total

def test_product_engine_handoff_difference_is_exactly_76(cli, wmj_home, imported, private_manifest, tmp_path):
    legacy = _run_frozen(cli, wmj_home, private_manifest, tmp_path, False)
    legacy_kept = {k for k, r in legacy.items() if r["dir"] and not r["excluded"]}
    handoff = _run_frozen(cli, wmj_home, private_manifest, tmp_path, True)
    handoff_kept = {k for k, r in handoff.items() if r["dir"] and not r["excluded"]}
    assert legacy_kept <= handoff_kept and len(handoff_kept - legacy_kept) == 76
