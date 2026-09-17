# tests/unit/panel/test_design_contract.py
"""面板视觉契约：模板是编译进包里的死文件，渲染只做一次标记替换，所以同一份代码每次产出同一套外壳。
这组用例守的不是像素，是"这套设计还在不在"——谁把卡片、令牌、深色模式、分页或吸顶表头删了，这里就红。
断言只挑结构与机制，不挑具体色值与间距，留出继续调细节的余地。"""
from where_my_job.panel.render import render_html, PanelSpec

SPEC = {"schema_version": 1, "title": "契约样本",
        "columns": ["tier", "score", "dir", "title", "company_name", "city", "salary_text", "exp", "degree", "report_state"],
        "charts": [{"type": "bar", "by": "dir"}, {"type": "bar", "by": "tier"}]}
META = {"as_of": "2026-09-17T10:29:31.123456Z", "match_run_id": "run_1", "campus": "已包含（由经验范围推导）",
        "input_selection": "latest", "warnings": [], "unmatched": 0,
        "groups": {"main": {"total": 2, "shown": 2, "truncated": False},
                   "excluded": {"rows": [], "total": 1, "shown": 1, "truncated": False},
                   "unknown": {"rows": [], "total": 0, "shown": 0, "truncated": False}}}
ROWS = [{"tier": "S", "score": 99.0, "dir": "AI产品经理", "title": "合成岗位甲", "company_name": "示例公司",
         "city": "合肥", "salary_text": "30-45K·15薪", "exp": "3-5年", "degree": "本科", "report_state": "none",
         "job_id": "boss:a", "job_url": "https://www.zhipin.com/job_detail/a.html"},
        {"tier": "B", "score": 70.0, "dir": "数据产品经理", "title": "合成岗位乙", "company_name": "演示公司",
         "city": "深圳", "salary_text": "20-30K", "exp": "1-3年", "degree": "本科", "report_state": "none",
         "job_id": "boss:b", "job_url": "https://www.zhipin.com/job_detail/b.html"}]

def _page() -> str:
    return render_html(PanelSpec.from_dict(SPEC), ROWS, META)

def test_design_tokens_and_dark_mode_survive():
    t = _page()
    for token in ("--bg:", "--card:", "--fg:", "--muted:", "--line:", "--acc:", "--shadow:", "--r:"):
        assert token in t, token
    assert "@media (prefers-color-scheme: dark)" in t
    assert t.count("--acc:") >= 2, "深色模式必须整套重定义令牌，而不是只改几处"
    assert "@media (max-width:899px)" in t, "窄屏断点"

def test_page_is_built_from_cards():
    t = _page()
    for cls in ('class="pagehead"', 'class="brand"', 'class="logo"', 'class="sub"', 'class="meta"',
                'class="tabs"', 'class="cards"', 'class="card', 'class="cardicon"', 'class="cardbody"',
                'class="filters"', 'class="sel"', 'class="searchbox"', 'class="vis"',
                'class="table-wrap"', 'class="tfoot"', 'class="pager"', 'class="foot"'):
        assert cls in t, cls
    assert 'role="tablist"' in t and 'class="statnum"' in t and 'class="track"' in t

def test_table_chrome_stays():
    t = _page()
    assert "thead th{position:sticky" in t, "表头吸顶"
    assert "#jobs th[aria-sort=" in t, "排序方向指示"
    assert all(f".tier-{x}{{" in t for x in "SABC"), "档位徽章配色"
    assert "font-variant-numeric:tabular-nums" in t, "数字等宽对齐"

def test_icons_are_inline_svg_not_fetched():
    t = _page()
    assert t.count("<svg") >= 10 and "<img" not in t
    assert "@import" not in t and "ur" + "l(" not in t
    assert "fonts.googleapis" not in t and "cdn." not in t

def test_shell_is_deterministic_for_the_same_input():
    assert _page() == _page()
