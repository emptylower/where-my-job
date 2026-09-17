# tests/integration/test_panel_timeline.py
import json
from tests.conftest import FIXTURES
from where_my_job.store import db, streams, events

E, S, L = FIXTURES / "events", FIXTURES / "streams", FIXTURES / "legacy"
DIARY = {"schema_version": 1, "stream": "custom.diary", "stream_revision": 1, "subject_kind": "none",
         "types": {"wrote": {"required": ["text"], "fields": {"text": "string"}}}}

def _spec(tmp_path, stream_names, enabled=True):
    from where_my_job.service.panel import DEFAULT_SPEC
    spec = json.loads(json.dumps(DEFAULT_SPEC, ensure_ascii=False))
    spec["timeline"] = {"enabled": enabled, "streams": stream_names}
    p = tmp_path / "panel-spec.json"; p.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return str(p)

def _write(tmp_path, name, obj):
    p = tmp_path / name; p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8"); return str(p)

def test_panel_timeline_two_custom_streams_escaped_and_single_pass(cli, clock, tmp_path, wmj_home):
    cli(["import", str(L / "合肥_AI产品经理.json")])
    assert cli(["stream", "register", "--file", str(S / "custom.interviews.v1.json")])[0] == 0
    assert cli(["stream", "register", "--file", _write(tmp_path, "diary.json", DIARY)])[0] == 0
    clock.advance(1)
    rc, env, _ = cli(["event", "add", "--file", str(E / "applied.json")]); app = env["data"]["application_id"]
    sched = json.loads((E / "scheduled.json").read_text(encoding="utf-8"))
    sched["subject_id"] = app; sched["payload"]["format"] = "<script>alert(1)</script>"
    clock.advance(1)
    assert cli(["event", "add", "--file", _write(tmp_path, "sched.json", sched)])[0] == 0
    diary_ev = {"schema_version": 1, "stream": "custom.diary", "stream_revision": 1, "type": "wrote", "subject_kind": "none",
                "occurred_at": "2026-09-12T00:00:00Z", "payload": {"text": "{{FILTER_JS}} 与 {{TIMELINE}}"},
                "idempotency_key": "syn-diary-0001", "origin": "user"}
    clock.advance(1)
    assert cli(["event", "add", "--file", _write(tmp_path, "diary-ev.json", diary_ev)])[0] == 0
    rc, env, _ = cli(["panel", "--spec", _spec(tmp_path, ["applications", "custom.interviews", "custom.diary", "applications"])])
    assert rc == 0, env
    html = wmj_home.panel_latest.read_text(encoding="utf-8")
    assert 'data-tab="timeline"' in html and 'data-tab-target="timeline"' in html
    assert html.count('data-tab-target="timeline"') == 1 and html.count('<section data-tab="timeline"') == 1   # 只有一个时间线按钮与区块
    assert "custom.interviews：显示 1 / 1（完整）" in html and "custom.diary：显示 1 / 1（完整）" in html
    assert html.count("applications：显示") == 1                        # 流名去重
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert html.count("<script") == 1                                   # 只有固定筛选脚本
    assert html.count("{{FILTER_JS}}") == 1 and html.count("{{TIMELINE}}") == 1   # 业务文本中的标记保持字面，不被二次解释
    assert "SYN-SECURITY" not in html and "SYN.lid" not in html

def test_panel_unregistered_stream_shows_empty_table_and_warns(cli, tmp_path, wmj_home):
    cli(["import", str(L / "合肥_AI产品经理.json")])
    rc, env, _ = cli(["panel", "--spec", _spec(tmp_path, ["custom.ghost"])])
    assert rc == 0
    html = wmj_home.panel_latest.read_text(encoding="utf-8")
    assert "custom.ghost：显示 0 / 0（未注册）" in html
    assert any("custom.ghost" in w for w in env["warnings"])

def test_panel_timeline_truncates_at_1000_and_reports_it(cli, conn, clock, tmp_path, wmj_home):
    cli(["import", str(L / "合肥_AI产品经理.json")])
    with db.write_tx(conn):
        streams.register(conn, clock, DIARY)
        for i in range(1001):
            events.append(conn, clock, {"schema_version": 1, "stream": "custom.diary", "stream_revision": 1, "type": "wrote",
                                        "subject_kind": "none", "subject_id": None, "occurred_at": "2026-09-12T00:00:00Z",
                                        "payload": {"text": f"第{i}条"}, "idempotency_key": f"syn-bulk-{i:05d}", "origin": "agent"})
    rc, env, _ = cli(["panel", "--spec", _spec(tmp_path, ["custom.diary"])])
    assert rc == 0
    html = wmj_home.panel_latest.read_text(encoding="utf-8")
    assert "custom.diary：显示 1000 / 1001（已截断）" in html
    assert any("被截断" in w for w in env["warnings"])

def test_panel_without_timeline_has_no_tab(cli, tmp_path, wmj_home):
    cli(["import", str(L / "合肥_AI产品经理.json")])
    rc, env, _ = cli(["panel"])
    html = wmj_home.panel_latest.read_text(encoding="utf-8")
    assert rc == 0 and 'data-tab="timeline"' not in html and 'data-tab-target="timeline"' not in html
    rc, env, _ = cli(["panel", "--spec", _spec(tmp_path, ["applications"], enabled=False)])
    html = wmj_home.panel_latest.read_text(encoding="utf-8")
    assert rc == 0 and 'data-tab="timeline"' not in html and 'data-tab-target="timeline"' not in html

def test_panel_spec_rejects_bad_timeline_stream_name(cli, tmp_path):
    # 流名格式由 02 的 panel.schema.json pattern 负责：格式错误是 SCHEMA_INVALID
    rc, env, _ = cli(["validate", "panel", _spec(tmp_path, ["Custom.Bad"])])
    assert rc == 1 and env["errors"][0]["code"] == "SCHEMA_INVALID" and env["errors"][0]["path"] == "$.timeline.streams[0]"

def test_panel_semantic_rejects_unregistered_stream_only_when_db_facts_given():
    from tests.conftest import load_fixture
    from where_my_job.validate import validate, Facts
    spec = load_fixture("panel.default.json")
    spec["timeline"] = {"enabled": True, "streams": ["applications", "custom.ghost"]}
    # 没有数据库事实（validate panel、面板渲染前的校验）：合法但未注册的流不报错，渲染时显示空表 + warning
    assert validate("panel", spec, Facts()) == []
    # 注入了活动流事实：未注册的合法流名是语义错误
    issues = validate("panel", spec, Facts(active_streams={"custom.interviews": {"stream": "custom.interviews"}}))
    assert [(i.code, i.path) for i in issues] == [("SEMANTIC_INVALID", "$.timeline.streams[1]")]
