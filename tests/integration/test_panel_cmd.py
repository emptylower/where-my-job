import json, pathlib, shutil
from tests.conftest import FIXTURES
from where_my_job import paths
L = FIXTURES / "legacy"

def _prep(cli, wmj_home, *, scoring_patch=None):
    cli(["import", str(L / "合肥_AI产品经理.json"), str(L / "合肥_产品经理.json")])
    sc = json.loads((FIXTURES / "scoring.minimal.json").read_text(encoding="utf-8"))
    if scoring_patch:
        scoring_patch(sc)
    wmj_home.config("scoring.json").write_text(json.dumps(sc, ensure_ascii=False), encoding="utf-8")
    shutil.copy(FIXTURES / "panel.default.json", wmj_home.config("panel.json"))
    shutil.copy(FIXTURES / "profile.synthetic.json", wmj_home.config("profile.json"))
    rc, env, _ = cli(["match"]); assert rc == 0, env

def test_panel_writes_latest_html_and_registers_output(cli, wmj_home):
    _prep(cli, wmj_home)
    rc, env, _ = cli(["panel"])
    assert rc == 0 and env["data"]["out"] == str(wmj_home.panel_latest) and env["data"]["rows"] >= 1
    g = env["data"]["groups"]
    assert g["main"]["total"] + g["excluded"]["total"] == 4 and g["excluded"]["total"] >= 1
    html = wmj_home.panel_latest.read_text(encoding="utf-8")
    assert "岗位面板" in html and "SYN-SECURITY" not in html and "SYN.lid" not in html and "raw_json" not in html
    assert "校园岗位" in html and "由经验范围推导" in html
    assert '<section data-tab="excluded"' in html and '<section data-tab="unknown"' in html
    managed = paths.managed_outputs(wmj_home)
    assert any(pathlib.Path(m["path"]).resolve() == wmj_home.panel_latest.resolve() for m in managed)

def test_excluded_group_shows_campus_exclusion(cli, wmj_home):
    _prep(cli, wmj_home, scoring_patch=lambda sc: sc.update(campus_policy="exclude"))
    rc, env, _ = cli(["panel"])
    assert rc == 0 and env["data"]["groups"]["excluded"]["total"] >= 1
    assert "校园岗位按经验范围推导为排除" in wmj_home.panel_latest.read_text(encoding="utf-8")

def test_panel_without_match_keeps_unevaluated_jobs_in_main(cli, wmj_home):
    cli(["import", str(L / "合肥_AI产品经理.json")])
    shutil.copy(FIXTURES / "panel.default.json", wmj_home.config("panel.json"))
    rc, env, _ = cli(["panel"])
    assert rc == 0 and any("尚未匹配" in w for w in env["warnings"])
    assert env["data"]["groups"]["main"]["total"] == 3 and env["data"]["unmatched"] == 3

def test_show_unknown_in_main_false_moves_unknowns_out(cli, wmj_home):
    _prep(cli, wmj_home)
    rc, env, _ = cli(["panel"]); with_unknown = env["data"]["groups"]["main"]["total"]
    spec = json.loads((FIXTURES / "panel.default.json").read_text(encoding="utf-8")); spec["show_unknown_in_main"] = False
    wmj_home.config("panel.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    rc, env, _ = cli(["panel"])
    assert rc == 0 and env["data"]["groups"]["unknown"]["total"] >= 1
    assert env["data"]["groups"]["main"]["total"] < with_unknown

def test_panel_out_path_checked_spec_validated_and_custom_out_registered(cli, wmj_home, tmp_path):
    _prep(cli, wmj_home)
    rc, env, _ = cli(["panel", "--out", str(wmj_home.browser_profile / "x.html")])
    assert rc == 1 and env["errors"][0]["code"] == "SEMANTIC_INVALID"
    bad = tmp_path / "p.json"; bad.write_text(json.dumps({"schema_version": 1, "columns": ["raw_json"]}))
    rc, env, _ = cli(["panel", "--spec", str(bad)])
    assert rc == 1 and env["errors"][0]["path"] == "$.columns[0]"
    out = tmp_path / "custom.html"
    rc, env, _ = cli(["panel", "--out", str(out)])
    assert rc == 0 and out.exists()
    assert any(pathlib.Path(m["path"]).resolve() == out.resolve() for m in paths.managed_outputs(wmj_home))
