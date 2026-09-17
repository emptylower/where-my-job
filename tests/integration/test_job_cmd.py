# tests/integration/test_job_cmd.py
from tests.conftest import FIXTURES
L = FIXTURES / "legacy"
A, B = str(L / "合肥_AI产品经理.json"), str(L / "合肥_产品经理.json")

def test_job_list_filters_and_shape(cli):
    cli(["import", A, B])
    rc, env, _ = cli(["job", "list", "--filter", "city=合肥", "--filter", "exp=1-3年", "--sort", "salary_hi", "--desc"])
    assert rc == 0
    d = env["data"]
    assert d["total"] >= 1 and d["page"] == 1 and d["truncated"] is False
    row = d["jobs"][0]
    assert set(row) >= {"job_id", "title", "job_url", "city", "salary_lo", "salary_hi", "exp", "degree",
                        "skills_json", "match_state", "report_state", "first_seen_at", "last_seen_at"}
    assert "raw_json" not in row and "SYN-SECURITY" not in str(row) and "lid" not in row

def test_comparison_operators_are_preserved(cli):
    cli(["import", A, B])
    rc, env, _ = cli(["job", "list", "--filter", "hit_count>=2"])
    assert rc == 0 and [j["job_id"] for j in env["data"]["jobs"]] == ["boss:SYN0001aaaa"]
    rc, env, _ = cli(["job", "list", "--filter", "exp!=1-3年"])
    assert rc == 0 and env["data"]["total"] == 3

def test_like_filter_is_literal(cli):
    cli(["import", A, B])
    rc, env, _ = cli(["job", "list", "--filter", "title~100%"])
    assert rc == 0 and env["data"]["total"] == 0
    rc, env, _ = cli(["job", "list", "--filter", "title~产品"])
    assert rc == 0 and env["data"]["total"] == 3

def test_job_show_paged_related_lists_and_no_private(cli):
    cli(["import", A, B])
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa"])
    assert rc == 0
    d = env["data"]
    assert d["job"]["job_url"] == "https://www.zhipin.com/job_detail/SYN0001aaaa.html"
    s = d["sightings"]
    assert s["total"] == 2 and s["page"] == 1 and s["page_size"] == 100 and s["truncated"] is False
    assert s["items"][0]["observed_at"] == "2026-09-14T03:25:00.000000Z"
    assert s["items"][0]["time_precision"] == "file_snapshot" and s["items"][0]["tz_assumption"] == "Asia/Shanghai"
    for key in ("attrs", "evidence", "reports", "applications"):
        assert d[key] == {"items": [], "total": 0, "page": 1, "page_size": 100, "truncated": False}
    assert "SYN-SECURITY" not in str(d) and "SYN.lid" not in str(d) and "raw_json" not in str(d)
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa", "--related-page-size", "1"])
    assert len(env["data"]["sightings"]["items"]) == 1 and env["data"]["sightings"]["truncated"] is True
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa", "--related-page-size", "1", "--related-page", "2"])
    assert len(env["data"]["sightings"]["items"]) == 1 and env["data"]["sightings"]["truncated"] is False

def test_job_show_errors(cli):
    cli(["import", A])
    rc, env, _ = cli(["job", "show", "boss:NOPE"])
    assert rc == 1 and env["errors"][0]["code"] == "NOT_FOUND"
    rc, env, _ = cli(["job", "show", "boss:SYN0001aaaa", "--related-page-size", "101"])
    assert rc == 1 and env["errors"][0]["code"] == "SEMANTIC_INVALID"

def test_job_list_bad_filters_exit_1(cli):
    rc, env, _ = cli(["job", "list", "--filter", "raw_json=1"])
    assert rc == 1 and env["errors"][0]["code"] == "SEMANTIC_INVALID"
    rc, env, _ = cli(["job", "list", "--filter", "salary_lo>=nan"])
    assert rc == 1 and env["errors"][0]["path"] == "$.filter.salary_lo"
