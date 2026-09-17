# tests/integration/test_evidence_cmd.py
import json
import os
import pytest
from tests.conftest import FIXTURES, load_fixture
from tests.helpers.evidence_seed import seed_job, seed_detail, seed_company_page
from where_my_job.store import db, runs, bundles

E = FIXTURES / "evidence"
JOB = "boss:SYN0001aaaa"

def _write(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p

def test_add_defaults_to_agent_and_is_idempotent(cli, conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    rc, env, _ = cli(["evidence", "add", JOB, "--file", str(E / "web_page.json")])
    assert rc == 0, env
    assert env["data"]["created"] is True and env["data"]["origin"] == "agent" and env["data"]["job_id"] == JOB
    eid = env["data"]["evidence_id"]
    rc, env, _ = cli(["evidence", "add", JOB, "--file", str(E / "web_page.json")])
    assert rc == 0 and env["data"]["created"] is False and env["data"]["evidence_id"] == eid

def test_add_origin_rules_and_unknown_job(cli, conn, clock, tmp_path):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    rc, env, _ = cli(["evidence", "add", JOB, "--file", str(E / "user_statement.json"), "--origin", "user"])
    assert rc == 0 and env["data"]["origin"] == "user"
    p = _write(tmp_path, "agent.json", dict(load_fixture("evidence/web_page.json"), origin="agent", idempotency_key="syn-ev-origin-0001"))
    rc, env, _ = cli(["evidence", "add", JOB, "--file", str(p), "--origin", "user"])
    assert rc == 1 and env["errors"][0]["path"] == "$.origin"
    p = _write(tmp_path, "cli.json", dict(load_fixture("evidence/web_page.json"), origin="cli", idempotency_key="syn-ev-origin-0002"))
    rc, env, _ = cli(["evidence", "add", JOB, "--file", str(p)])
    assert rc == 1
    p = _write(tmp_path, "ghost.json", dict(load_fixture("evidence/web_page.json"), job_id="boss:SYN0009zzzz"))
    rc, env, _ = cli(["evidence", "add", "boss:SYN0009zzzz", "--file", str(p)])
    assert rc == 1 and env["errors"][0]["code"] == "NOT_FOUND"
    assert conn.execute("select count(*) from evidence").fetchone()[0] == 1

def test_add_company_level_evidence_must_match_job_company(cli, conn, clock, tmp_path):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    seed_job(conn, clock, "boss:SYN0002bbbb", company_id="boss:SYNCO2", fixture_index=1)
    obj = dict(load_fixture("evidence/web_page.json"), idempotency_key="syn-ev-company-0001")
    obj.pop("job_id")
    ok = _write(tmp_path, "c1.json", dict(obj, company_id="boss:SYNCO1"))
    rc, env, _ = cli(["evidence", "add", JOB, "--file", str(ok)])
    assert rc == 0 and env["data"]["job_id"] is None and env["data"]["company_id"] == "boss:SYNCO1"
    bad = _write(tmp_path, "c2.json", dict(obj, company_id="boss:SYNCO2", idempotency_key="syn-ev-company-0002"))
    rc, env, _ = cli(["evidence", "add", JOB, "--file", str(bad)])
    assert rc == 1 and env["errors"][0]["code"] == "EVIDENCE_REF_INVALID"

def test_list_by_job_and_by_bundle_with_placeholder(cli, conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    c = seed_company_page(conn, clock, "boss:SYNCO1")
    with db.write_tx(conn):
        run_id = runs.create(conn, clock, kind="deepdive", config={}, planned=1)
        b = bundles.create(conn, clock, job_id=JOB, run_id=run_id, evidence_ids=[d, "ev_missing_0001", c],
                           acquisition_state="complete", unknowns=[])
    rc, env, _ = cli(["evidence", "list", "--job", JOB])
    assert rc == 0 and env["data"]["total"] == 2
    rc, env, _ = cli(["evidence", "list", "--bundle", b, "--limit", "2", "--offset", "1"])
    assert rc == 0 and env["data"]["total"] == 3 and env["data"]["truncated"] is False
    assert env["data"]["items"][0] == {"evidence_id": "ev_missing_0001", "missing": True}
    assert env["data"]["items"][1]["evidence_id"] == c
    rc, env, _ = cli(["evidence", "list", "--bundle", b, "--job", JOB])
    assert rc == 1
    rc, env, _ = cli(["evidence", "list", "--bundle", b, "--limit", "0"])
    assert rc == 1
    rc, env, _ = cli(["evidence", "list"])
    assert rc == 1

def test_show_minimized_and_url_stripped(cli, conn, clock):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB, url="https://www.zhipin.com/job_detail/SYN0001aaaa.html?lid=SYN.lid.1&securityId=SYN-SECURITY-1")
    rc, env, _ = cli(["evidence", "show", d])
    ev = env["data"]["evidence"]
    assert rc == 0 and ev["full_text_state"] == "present" and "full_text" not in ev
    assert ev["url"] == "https://www.zhipin.com/job_detail/SYN0001aaaa.html"
    text = json.dumps(env, ensure_ascii=False)
    assert "SYN-SECURITY" not in text and "SYN.lid" not in text and "SYNBOSS" not in text

def test_show_local_out_returns_only_metadata(cli, conn, clock, tmp_path):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    out = tmp_path / "full.txt"
    rc, env, _ = cli(["evidence", "show", d, "--local-out", str(out)])
    assert rc == 0, env
    assert env["data"] == {"evidence_id": d, "local_out": str(out.resolve()), "full_text_state": "present"}
    assert out.read_text(encoding="utf-8").startswith("职位描述")
    assert "职位描述" not in json.dumps(env, ensure_ascii=False)

@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root 会忽略目录权限")
def test_show_local_out_protected_is_1_and_os_permission_is_2(cli, conn, clock, wmj_home, tmp_path):
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    rc, env, _ = cli(["evidence", "show", d, "--local-out", str(wmj_home.browser_profile / "x.txt")])
    assert rc == 1 and env["errors"][0]["code"] == "SEMANTIC_INVALID"
    ro = tmp_path / "readonly"
    ro.mkdir()
    ro.chmod(0o500)
    try:
        rc, env, _ = cli(["evidence", "show", d, "--local-out", str(ro / "full.txt")])
        assert rc == 2 and env["errors"][0]["code"] == "PERMISSION_DENIED"
    finally:
        ro.chmod(0o700)

def test_show_not_found_and_pruned_text(cli, conn, clock, tmp_path):
    rc, env, _ = cli(["evidence", "show", "ev_nope"])
    assert rc == 1 and env["errors"][0]["code"] == "NOT_FOUND"
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    d = seed_detail(conn, clock, JOB)
    with db.write_tx(conn):
        conn.execute("update evidence set full_text=NULL, full_text_pruned_at='2026-09-14T12:00:00.000000Z' where evidence_id=?", (d,))
    out = tmp_path / "pruned.txt"
    rc, env, _ = cli(["evidence", "show", d, "--local-out", str(out)])
    assert rc == 1 and env["errors"][0]["code"] == "NOT_FOUND" and not out.exists()
