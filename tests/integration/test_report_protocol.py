# tests/integration/test_report_protocol.py
"""设计 v3 §7 报告事务协议 + §13 报告输入 × 采集状态组合。"""
import json
import pytest
from tests.conftest import load_fixture
from tests.helpers.evidence_seed import seed_job, seed_detail, seed_company_page
from tests.helpers.profile_seed import write_profile

JOB = "boss:SYN0001aaaa"

@pytest.fixture(autouse=True)
def _profile(wmj_home):
    write_profile(wmj_home, "example-minimal-v1")

def _rpt(tmp_path, name, bundle_id, detail_id, **over):
    text = json.dumps(load_fixture(f"reports/{name}.json"), ensure_ascii=False)
    r = json.loads(text.replace("__BUNDLE_ID__", bundle_id).replace("__DETAIL_EVIDENCE_ID__", detail_id))
    r.update(over)
    p = tmp_path / f"{name}-{r['idempotency_key']}.json"
    p.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    return p

def test_complete_acquisition_insufficient_conclusion_is_complete_report(cli, conn, clock, tmp_path):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    seed_company_page(conn, clock, "boss:SYNCO1")
    rc, env, _ = cli(["deepdive", JOB, "--cached"])
    b = env["data"]["bundle_id"]
    assert env["data"]["bundle"]["acquisition_state"] == "complete"
    rc, env, _ = cli(["report", "set", JOB, "--file", str(_rpt(tmp_path, "both_empty", b, d))])
    assert rc == 0 and env["data"]["report_state"] == "complete"
    rc, env, _ = cli(["report", "get", JOB])
    assert env["data"]["bundle"]["acquisition_state"] == "complete"
    assert env["data"]["structured"]["authentic"]["conclusion"] == "证据不足"

def test_partial_acquisition_explicit_unknowns_is_complete_report(cli, conn, clock, tmp_path):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    rc, env, _ = cli(["deepdive", JOB, "--cached", "--skip-company"])
    b = env["data"]["bundle_id"]
    assert env["data"]["bundle"]["acquisition_state"] == "partial"
    rc, env, _ = cli(["report", "set", JOB, "--file", str(_rpt(tmp_path, "partial", b, d))])
    assert rc == 0 and env["data"]["report_state"] == "complete"
    rc, env, _ = cli(["report", "get", JOB])
    assert env["data"]["bundle"]["acquisition_state"] == "partial"

def test_only_opposing_allows_long_listing_conclusion(cli, conn, clock, tmp_path):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    seed_company_page(conn, clock, "boss:SYNCO1")
    rc, env, _ = cli(["deepdive", JOB, "--cached"])
    b = env["data"]["bundle_id"]
    rc, env, _ = cli(["report", "set", JOB, "--file", str(_rpt(tmp_path, "only_opposing", b, d))])
    assert rc == 0, env
    rc, env, _ = cli(["job", "show", JOB])
    auth = json.loads(next(a["value_json"] for a in env["data"]["attrs"]["items"] if a["key"] == "authentic"))
    assert auth["conclusion"] == "倾向长期挂岗" and auth["conclusion_label"] == "推断" and auth["supporting"] == []

def test_bundle_alone_never_counts_as_deepdived(cli, conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    seed_detail(conn, clock, JOB)
    cli(["deepdive", JOB, "--cached"])
    rc, env, _ = cli(["job", "list", "--filter", "report_state=complete"])
    assert env["data"]["total"] == 0
    rc, env, _ = cli(["job", "list", "--filter", "report_state=analysis_pending"])
    assert env["data"]["total"] == 1

def test_signal_statements_never_claim_publish_date_or_continuity(cli, conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    seed_detail(conn, clock, JOB)
    rc, env, _ = cli(["deepdive", JOB, "--cached"])
    signals = env["data"]["bundle"]["signals"]
    for statement in (signals["observation_span"]["statement"], signals["up_date"]["statement"],
                      signals["company_counts"]["statement"]):
        for banned in ("发布于", "发布日期为", "持续招聘", "持续可见", "仍有编制", "养鱼"):
            assert banned not in statement
    assert "无法确认发布日期" in signals["up_date"]["statement"]
    assert signals["observation_as_of"] == env["data"]["bundle"]["signals"]["observation_span"]["as_of"]

def test_report_md_with_raw_html_rejected(cli, conn, clock, tmp_path):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    rc, env, _ = cli(["deepdive", JOB, "--cached"])
    b = env["data"]["bundle_id"]
    p = _rpt(tmp_path, "only_supporting", b, d, idempotency_key="syn-rpt-html-1")
    r = json.loads(p.read_text(encoding="utf-8"))
    r["report_md"] += "\n<img src=x onerror=alert(1)>"
    p.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["report", "set", JOB, "--file", str(p)])
    assert rc == 1 and env["errors"][0]["path"] == "$.report_md"
