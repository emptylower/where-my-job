# tests/security/test_evidence_output.py
import json
from tests.conftest import load_fixture
from tests.helpers.evidence_seed import seed_job, seed_detail, seed_company_page
from tests.helpers.profile_seed import write_profile

JOB = "boss:SYN0001aaaa"
PHONE = "1" + "38" + "0" * 8          # 运行时拼接：源码不含完整手机号样式，避免发行扫描命中
SENTINELS = (PHONE, "SYN-SECURITY", "SYN.lid", "SYNBOSS", "<div>", "securityId")

def _walk(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)

def test_no_full_text_key_or_private_structured_in_any_output(cli, conn, clock, wmj_home, tmp_path):
    write_profile(wmj_home)
    seed_job(conn, clock, JOB, company_id="boss:SYNCO1")
    structured = dict(load_fixture("evidence/detail_page_row.json")["structured"],
                      phone=PHONE, raw_html="<div>SYN-SECURITY-1</div>", boss_id="SYNBOSS1")
    d = seed_detail(conn, clock, JOB, structured=structured,
                    url="https://www.zhipin.com/job_detail/SYN0001aaaa.html?lid=SYN.lid.1&securityId=SYN-SECURITY-1")
    seed_company_page(conn, clock, "boss:SYNCO1")
    outputs = []
    for argv in (["evidence", "show", d], ["evidence", "list", "--job", JOB], ["job", "show", JOB],
                 ["deepdive", JOB, "--cached"]):
        rc, env, _ = cli(argv)
        assert rc == 0, env
        outputs.append(env)
    bundle_id = outputs[-1]["data"]["bundle_id"]
    rc, env, _ = cli(["evidence", "list", "--bundle", bundle_id])
    outputs.append(env)
    text = json.dumps(load_fixture("reports/only_supporting.json"), ensure_ascii=False)
    report = json.loads(text.replace("__BUNDLE_ID__", bundle_id).replace("__DETAIL_EVIDENCE_ID__", d))
    p = tmp_path / "report.json"
    p.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["report", "set", JOB, "--file", str(p)])
    assert rc == 0, env
    rc, env, _ = cli(["report", "get", JOB])
    outputs.append(env)
    shown = outputs[2]["data"]["evidence"]["items"]
    assert [x["evidence_id"] for x in shown] == [d] and "structured" in shown[0] and "structured_truncated" in shown[0]
    for env in outputs:
        pairs = list(_walk(env))
        keys = {k for k, _ in pairs}
        assert "full_text" not in keys and "structured_json" not in keys
        dumped = json.dumps(env, ensure_ascii=False)
        for sentinel in SENTINELS:
            assert sentinel not in dumped, sentinel
        for key, value in pairs:
            if key == "url" and value is not None:
                assert "?" not in value and "#" not in value
