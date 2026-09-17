# tests/integration/test_match_frozen.py
"""legacy-20260914 冻结输入：选择协议与七类损坏拒绝。全部使用合成数据。"""
import json, shutil
import pytest
from tests.conftest import FIXTURES
from where_my_job.ids import sha256_file
from where_my_job.store import db

L = FIXTURES / "legacy"
PROFILE = FIXTURES / "profile.synthetic.json"

def _write_legacy(path, scraped_at, title):
    rec = json.loads((L / "合肥_AI产品经理.json").read_text(encoding="utf-8"))["jobs"][0]
    rec = dict(rec, title=title)
    path.write_text(json.dumps({"keyword": "AI产品经理", "city": "合肥", "filters": {}, "filter_desc": [],
                                "scraped_at": scraped_at, "total": 1, "jobs": [rec]}, ensure_ascii=False), encoding="utf-8")
    return path

def _base_cfg():
    return {"schema_version": 2, "profile_revision": "synthetic-qc-to-aipm-v1", "campus_policy": "include",
            "classify": [{"dir": "AI产品经理", "when": {"field": "title", "match": "产品经理"}}],
            "exclude": [], "score": {"AI产品经理": {"base": 60, "base_reason": "合成冻结基分"}},
            "tiers": {"A": 60}, "fallback_tier": "D"}

def _frozen_cfg(paths):
    cfg = _base_cfg()
    cfg["input_selection"] = "legacy-20260914"
    cfg["legacy_input"] = {"files": sorted(({"name": p.name, "sha256": sha256_file(p)} for p in paths),
                                           key=lambda f: f["name"])}
    return cfg

@pytest.mark.parametrize("order", [("A", "B"), ("B", "A")])
def test_latest_vs_frozen_selection_independent_of_import_order(cli, wmj_home, tmp_path, order):
    shutil.copy(PROFILE, wmj_home.config("profile.json"))
    files = {"A": _write_legacy(tmp_path / "合肥_A.json", "2026-09-01T10:00:00", "AI产品经理"),
             "B": _write_legacy(tmp_path / "合肥_B.json", "2026-09-10T10:00:00", "会计")}
    for key in order:
        rc, env, _ = cli(["import", str(files[key])]); assert rc == 0, env
    latest = tmp_path / "latest.json"; latest.write_text(json.dumps(_base_cfg(), ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["match", "--scoring", str(latest)]); assert rc == 0, env
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa"])
    assert env["data"]["job"]["title"] == "会计" and env["data"]["job"]["dir"] is None          # latest：按观察时间最新
    frozen = tmp_path / "frozen.json"; frozen.write_text(json.dumps(_frozen_cfg(files.values()), ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["match", "--scoring", str(frozen)]); assert rc == 0, env
    assert env["data"]["input_selection"] == "legacy-20260914" and len(env["data"]["input_snapshot_hash"]) == 64
    assert any("冻结历史输入" in w for w in env["warnings"])
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa"])
    assert env["data"]["job"]["dir"] == "AI产品经理"                                           # 冻结：排序文件的首次旧 job_id
    assert env["data"]["job"]["match_state"] == "stale"                                          # 冻结事实不冒充当前条件
    assert any("冻结历史输入" in w for w in env["warnings"])

def _corrupt_setup(cli, wmj_home, tmp_path):
    shutil.copy(PROFILE, wmj_home.config("profile.json"))
    src = L / "合肥_AI产品经理.json"
    rc, env, _ = cli(["import", str(src)]); assert rc == 0, env
    frozen = tmp_path / "frozen.json"
    frozen.write_text(json.dumps(_frozen_cfg([src]), ensure_ascii=False), encoding="utf-8")
    return sha256_file(src), frozen

def test_frozen_baseline_succeeds(cli, wmj_home, tmp_path):
    _, frozen = _corrupt_setup(cli, wmj_home, tmp_path)
    rc, env, _ = cli(["match", "--scoring", str(frozen)])
    assert rc == 0 and env["data"]["jobs_evaluated"] == 3

CORRUPTIONS = {
    "raw_pruned": """update sightings set raw_json=NULL, raw_pruned_at='2026-09-14T12:00:00.000000Z' where file_sha256=:sha""",
    "last_item_deleted": """delete from sightings where file_sha256=:sha and item_index=2""",
    "source_name_forged": """update run_tasks set query_json=json_set(query_json, '$.source_name', '上海_AI产品经理.json')
                             where task_id in (select task_id from sightings where file_sha256=:sha)""",
    "missing_item_count": """update run_tasks set query_json=json_remove(query_json, '$.source_item_count')
                             where task_id in (select task_id from sightings where file_sha256=:sha)""",
    "raw_hash_mismatch": """update sightings set raw_json=json_set(raw_json, '$.title', '篡改') where file_sha256=:sha and item_index=0""",
    "record_errors_present": """update run_tasks set query_json=json_set(query_json, '$.record_errors', json('[{"item_index": 9, "message": "x"}]'))
                                where task_id in (select task_id from sightings where file_sha256=:sha)""",
    "task_running": """update run_tasks set status='running' where task_id in (select task_id from sightings where file_sha256=:sha)""",
}

@pytest.mark.parametrize("name", sorted(CORRUPTIONS))
def test_frozen_rejects_corrupted_inputs(cli, wmj_home, tmp_path, name):
    sha, frozen = _corrupt_setup(cli, wmj_home, tmp_path)
    c = db.open_db(wmj_home.db_path)
    try:
        c.execute(CORRUPTIONS[name], {"sha": sha})
    finally:
        c.close()
    rc, env, _ = cli(["match", "--scoring", str(frozen)])
    assert rc == 1 and env["errors"][0]["code"] in ("SEMANTIC_INVALID", "NOT_FOUND"), env
    rc, env, _ = cli(["status"])
    assert env["data"]["match"]["current_run_id"] is None
