from html.parser import HTMLParser
from where_my_job.panel.render import render_html, esc_text, esc_attr, safe_url, PanelSpec

class Surface(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.text = [], []
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
    def handle_data(self, data):
        self.text.append(data)

def _meta(**kw):
    base = {"as_of": "2026-09-14T12:00:00.000000Z", "match_run_id": "run_1", "campus": "已包含（由经验范围推导）",
            "input_selection": "latest", "warnings": [], "unmatched": 0,
            "groups": {"main": {"total": 1, "shown": 1, "truncated": False},
                       "excluded": {"rows": [], "total": 0, "shown": 0, "truncated": False},
                       "unknown": {"rows": [], "total": 0, "shown": 0, "truncated": False}}}
    base.update(kw)
    return base

def test_escapes_by_context():
    assert esc_text('<b>"x"&') == "&lt;b&gt;&quot;x&quot;&amp;"
    assert esc_attr("a\"b'c<") == "a&quot;b&#x27;c&lt;"

def test_safe_url_whitelist():
    assert safe_url("https://www.zhipin.com/job_detail/abc.html") == "https://www.zhipin.com/job_detail/abc.html"
    assert safe_url("https://www.zhipin.com/gongsi/SYNCO1.html") == "https://www.zhipin.com/gongsi/SYNCO1.html"
    assert safe_url("https://www.zhipin.com/job_detail/a.html?lid=xyz&securityId=1#f") == "https://www.zhipin.com/job_detail/a.html"
    for bad in ("javascript:alert(1)", "https://evil.example/x", "http://www.zhipin.com/job_detail/a.html",
                "https://www.zhipin.com:8443/job_detail/a.html", "https://user" + "@" + "www.zhipin.com/job_detail/a.html",
                "https://www.zhipin.com/job_detail/../x.html", "https://www.zhipin.com/job_detail/a b.html",
                "https://www.zhipin.com/web/geek/job", "https://[::1/job_detail/a.html", None, ""):
        assert safe_url(bad) is None, bad

def test_render_minimal_rows_single_script_no_external():
    spec = PanelSpec.from_dict({"schema_version": 1, "title": "T", "columns": ["title", "score"], "charts": [{"type": "bar", "by": "tier"}]})
    rows = [{"title": "AI产品经理", "score": 70.0, "tier": "B", "job_url": "https://www.zhipin.com/job_detail/x.html", "job_id": "boss:x"}]
    html = render_html(spec, rows, _meta())
    dom = Surface(); dom.feed(html)
    assert "<title>T</title>" in html and "AI产品经理" in html and 'data-col-tier="B"' in html
    assert sum(tag == "script" for tag, _ in dom.tags) == 1
    assert not any("src" in attrs for tag, attrs in dom.tags if tag in {"script", "img", "link", "iframe"})
    assert 'data-tab-target="main"' in html and 'data-tab-target="excluded"' in html and 'data-tab-target="unknown"' in html
    assert '<section data-tab="main">' in html and 'data-tab-target="timeline"' not in html

def test_business_text_template_markers_stay_literal():
    spec = PanelSpec.from_dict({"schema_version": 1, "title": "{{FILTER_JS}}", "columns": ["title"]})
    rows = [{"title": "{{FILTER_JS}} {{TBODY}} {{TIMELINE}}", "job_id": "boss:x"}]
    html = render_html(spec, rows, _meta())
    dom = Surface(); dom.feed(html)
    text = "".join(dom.text)
    assert "{{FILTER_JS}} {{TBODY}} {{TIMELINE}}" in text
    assert html.count('"use strict"') == 1

def test_excluded_and_unknown_groups_render_reasons():
    spec = PanelSpec.from_dict({"schema_version": 1, "columns": ["title"]})
    excluded = [{"job_id": "boss:e", "title": "校招岗", "exp": "在校/应届",
                 "exclusion_reasons_json": '[{"rule_id": "campus-policy", "reason": "校园岗位按经验范围推导为排除"}]'}]
    unknown = [{"job_id": "boss:u", "title": "日薪岗", "unknowns_json": '["salary_lo", "salary_hi"]', "match_state": "current"}]
    meta = _meta(groups={"main": {"total": 0, "shown": 0, "truncated": False},
                         "excluded": {"rows": excluded, "total": 3, "shown": 1, "truncated": True},
                         "unknown": {"rows": unknown, "total": 1, "shown": 1, "truncated": False}})
    html = render_html(spec, [], meta)
    assert "校园岗位按经验范围推导为排除" in html and "salary_lo、salary_hi" in html
    assert "已排除（1/3）" in html and "显示 1 / 3" in html

def test_timeline_marker_empty_without_rows():
    """时间线区块与页签由子计划 03 Task 9 提供；本计划未传入时间线数据时 {{TIMELINE}} 只留空。"""
    spec = PanelSpec.from_dict({"schema_version": 1, "columns": ["title"], "timeline": {"enabled": True, "streams": ["applications"]}})
    html = render_html(spec, [], _meta())
    assert "{{TIMELINE}}" not in html
    assert 'data-tab-target="timeline"' not in html and '<section data-tab="timeline"' not in html
    dom = Surface(); dom.feed(html)
    assert sum(tag == "script" for tag, _ in dom.tags) == 1
