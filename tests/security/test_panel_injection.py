# tests/security/test_panel_injection.py
import json, re, shutil
from html.parser import HTMLParser
from tests.conftest import FIXTURES
L = FIXTURES / "legacy"

class Surface(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
    def handle_data(self, data):
        self.text.append(data)

def _render(cli, wmj_home):
    cli(["import", str(L / "合肥_恶意样本.json")])
    shutil.copy(FIXTURES / "scoring.minimal.json", wmj_home.config("scoring.json"))
    shutil.copy(FIXTURES / "profile.synthetic.json", wmj_home.config("profile.json"))
    cli(["match"]); rc, env, _ = cli(["panel"]); assert rc == 0, env
    return wmj_home.panel_latest.read_text(encoding="utf-8")

def test_no_script_or_handler_injection(cli, wmj_home):
    page = _render(cli, wmj_home)
    dom = Surface()
    dom.feed(page)
    assert sum(tag == "script" for tag, _ in dom.tags) == 1
    assert not any(tag in {"img", "iframe", "object", "embed"} for tag, _ in dom.tags)
    for tag, attrs in dom.tags:
        assert not any(name.lower().startswith("on") for name in attrs)
        assert "srcdoc" not in attrs
        if tag in {"script", "link"}:
            assert "src" not in attrs and "href" not in attrs
    rendered_text = "".join(dom.text)
    assert "<script>alert(1)</script>" in rendered_text
    assert "rm -rf" in rendered_text

def test_template_markers_in_business_text_are_literal(cli, wmj_home):
    page = _render(cli, wmj_home)
    dom = Surface(); dom.feed(page)
    assert "{{FILTER_JS}} {{TBODY}} 模板标记样本" in "".join(dom.text)
    assert page.count('"use strict"') == 1

def test_links_only_canonical_https_zhipin(cli, wmj_home):
    page = _render(cli, wmj_home)
    dom = Surface(); dom.feed(page)
    hrefs = [attrs["href"] for tag, attrs in dom.tags if tag == "a" and "href" in attrs]
    assert hrefs and all(re.fullmatch(r"https://www\.zhipin\.com/job_detail/[A-Za-z0-9~_-]+\.html", h) for h in hrefs)
    assert "http://evil.example" in "".join(dom.text)

def test_no_external_resources_and_no_private_fields(cli, wmj_home):
    page = _render(cli, wmj_home)
    assert re.search(r'<(script|link|img|iframe)[^>]+src=', page) is None
    assert "@import" not in page and "url(" not in page
    for bad in ("SYN-SECURITY", "SYN.lid", "encrypt_boss_id", "raw_json"):
        assert bad not in page

def test_oversized_regex_rejected_before_eval(cli, wmj_home):
    cli(["import", str(L / "合肥_恶意样本.json")])
    sc = json.loads((FIXTURES / "scoring.minimal.json").read_text())
    sc["classify"][0]["when"] = {"field": "title", "match": "(a+)+" + "b" * 300}
    wmj_home.config("scoring.json").write_text(json.dumps(sc, ensure_ascii=False))
    rc, env, _ = cli(["match"])
    assert rc == 1 and "模式长度" in env["errors"][0]["message"]

def test_typed_filter_params_not_sql(cli, wmj_home):
    _render(cli, wmj_home)
    rc, env, _ = cli(["job", "list", "--filter", "title~' OR 1=1 --"])
    assert rc == 0 and env["data"]["total"] == 0
    rc, env, _ = cli(["job", "list", "--filter", "score>=1e999"])
    assert rc == 1
    rc, env, _ = cli(["job", "list", "--sort", "job_id; drop table jobs"])
    assert rc == 1 and env["errors"][0]["path"] == "$.sort"
