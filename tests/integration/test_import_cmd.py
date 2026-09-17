import json, shutil, sqlite3
from tests.conftest import FIXTURES
from where_my_job.ids import sha256_file

L = FIXTURES / "legacy"
A, B = str(L / "合肥_AI产品经理.json"), str(L / "合肥_产品经理.json")

def _db(wmj_home):
    # 经 open_db 打开：注册 wmj_as_of / wmj_profile_revision，子计划 02 起 v_jobs 依赖这些连接函数。
    from where_my_job.store import db
    return db.open_db(wmj_home.db_path)

def test_import_two_files_counts_and_idempotent(cli, wmj_home):
    rc, env, _ = cli(["import", A, B])
    assert rc == 0, env
    d = env["data"]
    assert d["files_ok"] == 2 and d["observations_inserted"] == 5 and d["jobs_total"] == 4
    assert env["run_id"].startswith("run_")
    rc2, env2, _ = cli(["import", A, B])
    assert rc2 == 0 and env2["data"]["observations_inserted"] == 0 and env2["data"]["observations_skipped"] == 5
    assert env2["data"]["jobs_total"] == 4
    c = _db(wmj_home)
    task = c.execute("select task_key, query_json from run_tasks where run_id=? order by task_key", (env["run_id"],)).fetchall()
    assert [t["task_key"] for t in task] == ["000000:合肥_AI产品经理.json", "000001:合肥_产品经理.json"]
    q = json.loads(task[0]["query_json"])
    assert q["source_name"] == "合肥_AI产品经理.json" and q["source_index"] == 0
    assert q["source_item_count"] == 3 and q["record_errors"] == [] and q["sha256"] == sha256_file(A)
    s = c.execute("select tz_assumption, observed_at from sightings limit 1").fetchone()
    assert s["tz_assumption"] == "Asia/Shanghai" and s["observed_at"].endswith("Z")
    assert list((wmj_home.runs_dir).glob("*.lock")) == []

def test_import_partial_bad_file_exit_4_with_top_level_run_id(cli, wmj_home):
    rc, env, _ = cli(["import", A, str(L / "broken.json")])
    assert rc == 4 and env["status"] == "partial" and env["errors"][0]["code"] == "SOME_FILES_INVALID"
    assert env["run_id"].startswith("run_")
    assert env["data"]["observations_inserted"] == 3 and env["data"]["files_failed"] == ["broken.json"]
    assert _db(wmj_home).execute("select status from runs where run_id=?", (env["run_id"],)).fetchone()[0] == "partial"

def test_import_all_bad_exit_1_and_no_run(cli, wmj_home):
    rc, env, _ = cli(["import", str(L / "broken.json")])
    assert rc == 1 and env["errors"][0]["code"] == "ALL_FILES_INVALID" and env["run_id"] is None
    assert _db(wmj_home).execute("select count(*) from runs").fetchone()[0] == 0

def test_file_whose_records_all_lack_ids_is_exit_1(cli, tmp_path):
    p = tmp_path / "合肥_x.json"
    p.write_text(json.dumps({"scraped_at": "2026-09-14T11:00:00", "jobs": [{"title": "a"}, {"title": "b"}]}))
    rc, env, _ = cli(["import", str(p)])
    assert rc == 1 and env["errors"][0]["code"] == "ALL_FILES_INVALID"

def test_record_errors_make_result_partial(cli, tmp_path):
    data = json.loads((L / "合肥_AI产品经理.json").read_text(encoding="utf-8"))
    data["jobs"].append({"title": "missing id"})
    p = tmp_path / "合肥_AI产品经理.json"; p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["import", str(p)])
    assert rc == 4 and env["errors"][0]["code"] == "SOME_FILES_INVALID"
    assert env["data"]["record_errors"] == 1 and env["data"]["observations_inserted"] == 3

def test_manifest_relative_paths_and_sha_check(cli, tmp_path):
    m = tmp_path / "m"; m.mkdir()
    shutil.copy(A, m / "合肥_AI产品经理.json"); shutil.copy(B, m / "合肥_产品经理.json")
    man = {"schema_version": 1, "timezone_assumption": "Asia/Shanghai",
           "files": [{"path": "合肥_AI产品经理.json", "sha256": sha256_file(A)},
                     {"path": "合肥_产品经理.json", "sha256": "0" * 64}]}
    (m / "manifest.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["import", "--manifest", str(m / "manifest.json")])
    assert rc == 4 and env["data"]["files_ok"] == 1 and "sha256" in json.dumps(env["errors"], ensure_ascii=False)

def test_same_basename_in_two_dirs_and_duplicate_args(cli, tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    shutil.copy(A, tmp_path / "a" / "合肥_AI产品经理.json")
    data = json.loads((L / "合肥_AI产品经理.json").read_text(encoding="utf-8"))
    data["jobs"][0]["title"] = "AI产品经理（改）"
    (tmp_path / "b" / "合肥_AI产品经理.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    a_path = str(tmp_path / "a" / "合肥_AI产品经理.json")
    rc, env, _ = cli(["import", a_path, str(tmp_path / "b" / "合肥_AI产品经理.json"), a_path])
    assert rc == 0, env
    assert env["data"]["files_ok"] == 2 and env["data"]["observations_inserted"] == 6 and env["data"]["jobs_total"] == 3

def test_conflicting_sha_for_same_path_is_input_error(cli, tmp_path):
    shutil.copy(A, tmp_path / "合肥_AI产品经理.json")
    man = {"schema_version": 1, "files": [{"path": "合肥_AI产品经理.json", "sha256": "1" * 64},
                                         {"path": "./合肥_AI产品经理.json", "sha256": "2" * 64}]}
    (tmp_path / "m.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["import", "--manifest", str(tmp_path / "m.json")])
    assert rc == 1 and env["errors"][0]["code"] == "SEMANTIC_INVALID"

def test_newer_fact_wins_regardless_of_import_order(cli, wmj_home):
    cli(["import", B])
    cli(["import", A])
    row = _db(wmj_home).execute("select last_seen_at, hit_count, seen_run_count, title, salary_text from v_jobs "
                                "where job_id='boss:SYN0001aaaa'").fetchone()
    assert row["last_seen_at"] == "2026-09-14T03:25:00.000000Z" and row["hit_count"] == 2 and row["seen_run_count"] == 2
    assert row["salary_text"] == "16-26K·14薪"

def test_missing_scraped_at_stores_null_time(cli, tmp_path, wmj_home):
    data = json.loads((L / "合肥_AI产品经理.json").read_text(encoding="utf-8"))
    del data["scraped_at"]
    p = tmp_path / "合肥_AI产品经理.json"; p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["import", str(p)])
    assert rc == 0
    c = _db(wmj_home)
    assert c.execute("select count(*) from sightings where observed_at is null and tz_assumption is null").fetchone()[0] == 3
    assert c.execute("select first_seen_at from jobs where job_id='boss:SYN0001aaaa'").fetchone()[0] is None

def test_resource_failure_on_second_file_keeps_first_committed(cli, wmj_home, monkeypatch):
    from where_my_job.store import sightings
    original = sightings.insert
    def failing(conn, clock, **kw):
        if kw["job_id"] == "boss:SYN0004dddd":
            raise sqlite3.OperationalError("disk I/O error")
        return original(conn, clock, **kw)
    monkeypatch.setattr(sightings, "insert", failing)
    rc, env, _ = cli(["import", A, B])
    assert rc == 4 and env["errors"][0]["code"] == "PARTIAL_RESULT" and env["run_id"].startswith("run_")
    assert env["data"]["files_committed"] == ["合肥_AI产品经理.json"]
    assert env["data"]["files_unfinished"] == ["合肥_产品经理.json"]
    c = _db(wmj_home)
    assert c.execute("select count(*) from sightings").fetchone()[0] == 3
    j = c.execute("select hit_count, current_sighting_id from jobs where job_id='boss:SYN0001aaaa'").fetchone()
    assert j["hit_count"] == 1 and j["current_sighting_id"] is not None
    assert c.execute("select status from runs where run_id=?", (env["run_id"],)).fetchone()[0] == "partial"
