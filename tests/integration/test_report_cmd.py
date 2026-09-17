# tests/integration/test_report_cmd.py
import json
import pytest
from tests.conftest import FIXTURES, load_fixture
from tests.helpers.evidence_seed import seed_job, seed_detail, seed_company_page
from tests.helpers.profile_seed import write_profile

JOB = "boss:SYN0001aaaa"

@pytest.fixture(autouse=True)
def _profile(wmj_home):
    write_profile(wmj_home, "example-minimal-v1")

def _write_report(tmp_path, name, bundle_id, detail_id, **over):
    text = json.dumps(load_fixture(f"reports/{name}.json"), ensure_ascii=False)
    r = json.loads(text.replace("__BUNDLE_ID__", bundle_id).replace("__DETAIL_EVIDENCE_ID__", detail_id))
    r.update(over)
    p = tmp_path / f"{name}-{r['idempotency_key']}.json"
    p.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    return p

def _prep(cli, conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    seed_company_page(conn, clock, "boss:SYNCO1")
    rc, env, _ = cli(["deepdive", JOB, "--cached"])
    assert rc == 0, env
    return env["data"]["bundle_id"], d

def _add_web(cli, tmp_path, key, url):
    obj = dict(load_fixture("evidence/web_page.json"), idempotency_key=key, url=url)
    p = tmp_path / f"{key}.json"
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["evidence", "add", JOB, "--file", str(p)])
    assert rc == 0, env
    return env["data"]["evidence_id"]

def test_set_then_get_complete(cli, conn, clock, tmp_path):
    b, d = _prep(cli, conn, clock)
    rc, env, _ = cli(["report", "set", JOB, "--file", str(_write_report(tmp_path, "only_supporting", b, d))])
    assert rc == 0, env
    assert env["data"] == {"report_id": env["data"]["report_id"], "bundle_id": b, "bundle_version": 1,
                           "report_state": "complete", "created": True}
    rid = env["data"]["report_id"]
    rc, env, _ = cli(["report", "get", JOB])
    assert rc == 0 and env["data"]["report_id"] == rid and env["data"]["is_current"] is True
    assert env["data"]["structured"]["authentic"]["conclusion_label"] == "推断"
    rc, env, _ = cli(["job", "show", JOB])
    assert env["data"]["job"]["report_state"] == "complete" and env["data"]["job"]["report_id"] == rid
    assert {a["key"] for a in env["data"]["attrs"]["items"]} >= {"authentic", "jd_translation"}

def test_extra_evidence_derives_bundle_and_reference_only_in_extra_is_allowed(cli, conn, clock, tmp_path):
    b, d = _prep(cli, conn, clock)
    web = _add_web(cli, tmp_path, "syn-ev-extra-cmd-1", "https://example.com/extra/1")
    p = _write_report(tmp_path, "only_supporting", b, d, extra_evidence_ids=[web])
    r = json.loads(p.read_text(encoding="utf-8"))
    r["authentic"]["supporting"][0]["evidence_id"] = web
    p.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["report", "set", JOB, "--file", str(p)])
    assert rc == 0, env
    assert env["data"]["bundle_id"] != b and env["data"]["bundle_version"] == 2 and env["data"]["report_state"] == "complete"
    rc, env, _ = cli(["report", "get", JOB])
    assert web in [e["evidence_id"] for e in env["data"]["bundle"]["evidence"]]

def test_rejects_foreign_ref_ref_outside_closure_and_stale_bundle(cli, conn, clock, tmp_path):
    b, d = _prep(cli, conn, clock)
    seed_job(conn, clock, "boss:SYN0009zzzz", company_id="boss:SYNCO2", fixture_index=1)
    d9 = seed_detail(conn, clock, "boss:SYN0009zzzz")
    rc, env, _ = cli(["report", "set", JOB, "--file", str(_write_report(tmp_path, "only_supporting", b, d9))])
    assert rc == 1 and env["errors"][0]["code"] == "EVIDENCE_REF_INVALID"
    web = _add_web(cli, tmp_path, "syn-ev-outside-cmd-1", "https://example.com/outside/1")
    p = _write_report(tmp_path, "only_supporting", b, d, idempotency_key="syn-rpt-outside-1")
    r = json.loads(p.read_text(encoding="utf-8"))
    r["authentic"]["supporting"][0]["evidence_id"] = web
    p.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["report", "set", JOB, "--file", str(p)])
    assert rc == 1 and env["errors"][0]["code"] == "EVIDENCE_REF_INVALID"
    clock.advance(1)
    rc, env, _ = cli(["deepdive", JOB, "--cached"])
    rc, env, _ = cli(["report", "set", JOB, "--file", str(_write_report(tmp_path, "only_supporting", b, d, idempotency_key="syn-rpt-stale-1"))])
    assert rc == 1 and env["errors"][0]["code"] == "BUNDLE_STALE"
    rc, env, _ = cli(["job", "show", JOB])
    assert env["data"]["job"]["report_state"] == "analysis_pending"
    assert conn.execute("select count(*) from deepdives").fetchone()[0] == 0

def test_retry_after_new_bundle_returns_original(cli, conn, clock, tmp_path):
    b, d = _prep(cli, conn, clock)
    p = _write_report(tmp_path, "only_supporting", b, d)
    rc, env1, _ = cli(["report", "set", JOB, "--file", str(p)])
    clock.advance(1)
    cli(["deepdive", JOB, "--cached"])
    rc, env2, _ = cli(["report", "set", JOB, "--file", str(p)])
    assert rc == 0 and env2["data"]["created"] is False and env2["data"]["report_id"] == env1["data"]["report_id"]
    assert env2["data"]["report_state"] == "stale"

def test_set_incomplete_report_keeps_pending(cli, conn, clock, tmp_path):
    b, d = _prep(cli, conn, clock)
    p = _write_report(tmp_path, "both_empty", b, d)
    r = json.loads(p.read_text(encoding="utf-8"))
    r["authentic"]["conclusion"] = "倾向真实在招"
    p.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["report", "set", JOB, "--file", str(p)])
    assert rc == 1 and env["errors"][0]["code"] == "REPORT_INCOMPLETE"
    rc, env, _ = cli(["job", "show", JOB])
    assert env["data"]["job"]["report_state"] == "analysis_pending"
    rc, env, _ = cli(["report", "get", JOB])
    assert rc == 1 and env["errors"][0]["code"] == "NOT_FOUND"

def test_set_idempotent_and_conflict(cli, conn, clock, tmp_path):
    b, d = _prep(cli, conn, clock)
    p = _write_report(tmp_path, "only_supporting", b, d)
    rc, env1, _ = cli(["report", "set", JOB, "--file", str(p)])
    rc, env2, _ = cli(["report", "set", JOB, "--file", str(p)])
    assert rc == 0 and env2["data"]["created"] is False and env2["data"]["report_id"] == env1["data"]["report_id"]
    r = json.loads(p.read_text(encoding="utf-8"))
    r["report_md"] += "\n改"
    p.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["report", "set", JOB, "--file", str(p)])
    assert rc == 1 and env["errors"][0]["code"] == "IDEMPOTENCY_CONFLICT"

def test_get_history_report_marked_stale(cli, conn, clock, tmp_path):
    b, d = _prep(cli, conn, clock)
    rc, env, _ = cli(["report", "set", JOB, "--file", str(_write_report(tmp_path, "only_supporting", b, d))])
    rid1 = env["data"]["report_id"]
    clock.advance(1)
    rc, env, _ = cli(["deepdive", JOB, "--cached"])
    b2 = env["data"]["bundle_id"]
    rc, env, _ = cli(["report", "set", JOB, "--file", str(_write_report(tmp_path, "partial", b2, d))])
    rid2 = env["data"]["report_id"]
    rc, env, _ = cli(["report", "get", JOB, "--report-id", rid1])
    assert rc == 0 and env["data"]["report_state"] == "stale" and env["data"]["is_current"] is False
    rc, env, _ = cli(["report", "get", JOB])
    assert env["data"]["report_id"] == rid2 and env["data"]["report_state"] == "complete"
    assert [h["report_id"] for h in env["data"]["history"]] == [rid2, rid1]

def test_profile_change_makes_report_stale(cli, conn, clock, wmj_home, tmp_path):
    b, d = _prep(cli, conn, clock)
    cli(["report", "set", JOB, "--file", str(_write_report(tmp_path, "only_supporting", b, d))])
    write_profile(wmj_home, "example-minimal-v2")
    rc, env, _ = cli(["job", "show", JOB])
    assert env["data"]["job"]["report_state"] == "stale"
    rc, env, _ = cli(["report", "get", JOB])
    assert env["data"]["report_state"] == "stale"
    write_profile(wmj_home, "example-minimal-v1")
    rc, env, _ = cli(["job", "show", JOB])
    assert env["data"]["job"]["report_state"] == "complete"

def test_validate_report_uses_db_facts_and_does_not_write(cli, conn, clock, tmp_path):
    b, d = _prep(cli, conn, clock)
    rc, env, _ = cli(["validate", "report", str(_write_report(tmp_path, "only_supporting", b, d))])
    assert rc == 0 and env["data"] == {"kind": "report", "issues": []}
    rc, env, _ = cli(["validate", "report", str(_write_report(tmp_path, "only_supporting", "bundle_nope", d, idempotency_key="syn-rpt-validate-2"))])
    assert rc == 1 and env["errors"][0]["code"] == "NOT_FOUND"
    rc, env, _ = cli(["validate", "evidence", str(FIXTURES / "evidence" / "web_page.json")])
    assert rc == 0
    assert conn.execute("select count(*) from deepdives").fetchone()[0] == 0
    assert conn.execute("select count(*) from evidence where kind='web_page'").fetchone()[0] == 0

def test_validate_bad_json_is_schema_invalid(cli, tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{oops", encoding="utf-8")
    rc, env, _ = cli(["validate", "report", str(p)])
    assert rc == 1 and env["errors"][0]["code"] == "SCHEMA_INVALID"

def test_validate_report_type_error_is_schema_invalid_before_db(cli, tmp_path):
    r = json.loads(json.dumps(load_fixture("reports/only_supporting.json"), ensure_ascii=False))
    r["job_id"] = [JOB]
    p = tmp_path / "array-job.json"
    p.write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["validate", "report", str(p)])
    assert rc == 1 and env["errors"][0]["code"] == "SCHEMA_INVALID"
    assert env["errors"][0]["path"].startswith("$.job_id")
