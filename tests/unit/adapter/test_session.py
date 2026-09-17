import pytest
from tests.conftest import load_fixture
from tests.helpers.fake_transport import FakeTransport
from where_my_job.adapter.session import BrowserSession, NavigationRefused

SEARCH = "https://www.zhipin.com/web/geek/job?query=AI%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86&city=101220100&page=1&experience=101"
JOB = "https://www.zhipin.com/job_detail/SYN0101aaaa.html"
COMPANY = "https://www.zhipin.com/gongsi/SYNCO1.html"

def _s(script, **kw):
    t = FakeTransport(script, **kw)
    return BrowserSession(t, capture_timeout=5.0, monotonic=lambda: 0.0), t

def _search(s):
    return s.search_page("AI产品经理", "101220100", 1, {"experience": "101"})

def test_first_page_bound_to_navigation():
    s, t = _s([("joblist", load_fixture("api/page1_ok.json"))])
    r = _search(s)
    assert (r.kind, r.request_id) == ("success", "req-1-1-0") and t.navigations == [SEARCH] and t.documents_sent == [SEARCH]

def test_next_page_scrolls_and_matches_page_number():
    s, t = _s([("joblist", load_fixture("api/page1_ok.json")), ("joblist", load_fixture("api/page2_ok.json"))])
    _search(s)
    r = s.next_page(2)
    assert r.kind == "success" and t.scrolls == 1 and len(t.navigations) == 1

@pytest.mark.parametrize("opts,code", [
    ({"query": {"page": "999"}}, "other_parameters"), ({"query": {"city": "101010100"}}, "other_parameters"),
    ({"query": {"experience": "104"}}, "other_parameters"),
    ({"url": "https://evil.example/wapi/zpgeek/search/joblist.json?query=x"}, "other_endpoint"),
    ({"url": "https://www.zhipin.com/wapi/zpgeek/other.json"}, "other_endpoint"),
    ({"before_action": True}, "before_action"), ({"loader_id": "L-old"}, "other_document"),
])
def test_unrelated_responses_are_ignored_then_timeout(opts, code):
    s, t = _s([("joblist", load_fixture("api/page1_ok.json"), opts)])
    r = _search(s)
    assert (r.kind, r.reason, r.ignored_responses) == ("unknown", "capture_timeout", 1)
    assert r.ignored_reasons == {code: 1}

def test_other_session_response_is_counted_under_its_own_code():
    s, _ = _s([("foreign", load_fixture("api/page1_ok.json")), ("timeout",)])
    r = _search(s)
    assert r.ignored_reasons == {"other_session": 1} and r.ignored_responses == 1

JOBLIST = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json"

def test_parameter_mismatch_is_named_in_the_notes():
    """参数不符要说清是哪一项：地址只留参数名，判定只留不符类型，参数值一概不记。"""
    s, _ = _s([("joblist", load_fixture("api/page1_ok.json"), {"query": {"page": "999"}}), ("timeout",)])
    r = _search(s)
    assert r.ignored_reasons == {"other_parameters": 1}
    assert r.notes[0] == f"capture:other_parameters:{JOBLIST}?[city,experience,page,query]"
    assert r.notes[1] == "params:page=differs"
    assert r.notes[2] == "body:success,items=2,code=0,has_more=true"
    assert r.notes[3].startswith("landing:")
    joined = "".join(r.notes)
    assert "101220100" not in joined and "999" not in joined and "%E4%BA%A7" not in joined

def test_response_carrying_no_search_parameters_is_bound_by_document_only():
    """地址上一个必需参数都没有：靠文档与顺序绑定认领，并把这个事实记进诊断。"""
    s, _ = _s([("joblist", load_fixture("api/page1_ok.json"), {"url": f"{JOBLIST}?_=1789554458415"})])
    r = _search(s)
    assert (r.kind, r.reason) == ("success", "ok")
    assert r.notes == ("bound:document_only",)

def test_response_carrying_some_parameters_is_checked_against_them():
    """带了部分参数：这些必须一致，通过后不记 bound:（还有可核对的东西）。"""
    s, _ = _s([("joblist", load_fixture("api/page1_ok.json"),
                {"url": f"{JOBLIST}?city=101220100&page=1&experience=101"})])
    r = _search(s)
    assert (r.kind, r.reason) == ("success", "ok") and r.notes == ()

def test_duplicated_required_parameter_is_named_in_the_notes():
    url = (f"{JOBLIST}?query=AI%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86&city=101220100"
           "&page=1&page=1&experience=101")
    s, _ = _s([("joblist", load_fixture("api/page1_ok.json"), {"url": url}), ("timeout",)])
    r = _search(s)
    assert r.notes[1] == "params:page=duplicated"
    assert r.notes[2] == "body:success,items=2,code=0,has_more=true"

def test_non_parameter_discard_records_only_the_address_note():
    """端点不符这类丢弃只记地址：逐项判定对它没有意义。"""
    s, _ = _s([("joblist", load_fixture("api/page1_ok.json"),
                {"url": "https://evil.example/wapi/zpgeek/search/joblist.json?query=x"}), ("timeout",)])
    r = _search(s)
    assert r.notes[0] == "capture:other_endpoint:https://evil.example/wapi/zpgeek/search/joblist.json?[query]"
    assert not any(n.startswith("params:") for n in r.notes)
    assert r.notes[1] == "body:success,items=2,code=0,has_more=true"   # 端点不符也要知道对方给没给数据

def test_discard_notes_never_carry_job_content():
    """这一行是本计划的安全边界：诊断里不得出现任何岗位字段。"""
    s, _ = _s([("joblist", load_fixture("api/page1_ok.json"), {"query": {"page": "999"}}), ("timeout",)])
    joined = "".join(_search(s).notes)
    for word in ("jobName", "brandName", "salaryDesc", "encryptJobId", "lid", "securityId"):
        assert word not in joined

def test_foreign_session_blocked_response_changes_nothing():
    s, _ = _s([("foreign", load_fixture("api/page2_code37.json")), ("joblist", load_fixture("api/page1_ok.json"))])
    r = _search(s)
    assert r.kind == "success" and r.ignored_responses == 1

def test_own_session_risk_response_wins_even_if_not_matching():
    s, _ = _s([("joblist", load_fixture("api/page2_code37.json"), {"query": {"page": "5"}})])
    r = _search(s)
    assert (r.kind, r.platform_code) == ("blocked", 37)

@pytest.mark.parametrize("status,kind", [(401, "unauthenticated"), (403, "blocked"), (429, "blocked"), (500, "unknown")])
def test_real_http_status_is_not_rewritten(status, kind):
    s, _ = _s([("joblist", load_fixture("api/page1_ok.json"), {"http_status": status})])
    assert _search(s).kind == kind

def test_load_failure_and_body_missing_stop():
    s, _ = _s([("load_failed",)])
    r = _search(s)
    assert (r.kind, r.reason) == ("unknown", "load_failed")
    s, _ = _s([("joblist", None)])
    assert _search(s).reason == "body_unavailable"

@pytest.mark.parametrize("target,kind,reason", [
    ("https://www.zhipin.com/web/user/?ka=header-login", "unauthenticated", "login_redirect"),
    ("https://www.zhipin.com/web/common/security-check.html?seed=x", "blocked", "risk_redirect"),
    ("https://www.zhipin.com/web/passport/zp/verify.html?seed=x", "blocked", "risk_redirect"),
    ("https://evil.example/landing", "unknown", "unexpected_document"),
])
def test_login_verification_and_offsite_redirects_are_refused_before_sending(target, kind, reason):
    s, t = _s([("redirect", target), ("joblist", load_fixture("api/page1_ok.json"))])
    r = _search(s)
    assert (r.kind, r.reason) == (kind, reason) and target not in t.documents_sent

def test_cross_domain_subframe_refused_but_page_continues():
    s, t = _s([("subframe", "https://evil.example/frame"), ("joblist", load_fixture("api/page1_ok.json"))])
    r = _search(s)
    assert r.kind == "success" and r.refused_subframes == 1
    assert "https://evil.example/frame" not in t.documents_sent

def test_new_main_document_during_scroll_is_classified_by_landing():
    """翻页期间页面跳到验证页：拦截已关，文档会加载，但落点判定照样判风控——退出 3 与冷却不变。"""
    s, t = _s([("joblist", load_fixture("api/page1_ok.json")), ("new_document", "https://www.zhipin.com/web/common/security-check.html"),
               ("joblist", load_fixture("api/page2_ok.json"))])
    _search(s)
    r = s.next_page(2)
    assert (r.kind, r.reason) == ("blocked", "risk_page")

def test_detail_read_uses_same_page_for_both_evaluations():
    s, t = _s([("page", load_fixture("pages/job_detail_ok.json")), ("page", load_fixture("pages/company_ok.json"))])
    d = s.open_job_detail("SYN0101aaaa")
    assert d.kind == "ok" and d.extracted["jd"].startswith("职位描述") and t.evaluations == 2
    c = s.open_company("SYNCO1")
    assert c.kind == "ok" and "在招职位" in c.extracted["page_text"] and t.evaluations == 4
    assert t.navigations == [JOB, COMPANY]

def test_detail_risk_and_login_pages_are_classified_before_parsing():
    wall = load_fixture("pages/job_detail_login_wall.json")
    risk = load_fixture("pages/job_detail_risk.json")
    s, _ = _s([("page", wall)])
    assert s.open_job_detail("SYN0101aaaa").kind == "unauthenticated"
    s, _ = _s([("page", risk)])
    d = s.open_job_detail("SYN0101aaaa")
    assert (d.kind, d.reason, d.extracted) == ("blocked", "risk_page", None)

def test_verification_engineer_job_is_not_risk():
    page = load_fixture("pages/job_detail_ok.json")
    page["jd"] = "职位描述\n芯片验证工程师，负责 UVM 验证平台搭建与回归。" + "说明" * 80
    s, _ = _s([("page", page)])
    assert s.open_job_detail("SYN0101aaaa").kind == "ok"

def test_snapshot_url_mismatch_rejected():
    page = load_fixture("pages/job_detail_ok.json"); page["url"] = "https://www.zhipin.com/job_detail/SYN0000other.html"
    s, _ = _s([("page", page)])
    d = s.open_job_detail("SYN0101aaaa")
    assert (d.kind, d.reason) == ("unknown", "snapshot_url_mismatch")

@pytest.mark.parametrize("bad", ["../etc/passwd", "x.html?lid=abc", "", "a" * 129, "SYN 1"])
def test_ids_are_validated_before_navigation(bad):
    s, t = _s([])
    with pytest.raises(NavigationRefused):
        s.open_job_detail(bad)
    assert t.navigations == []

def test_offsite_subframe_is_recorded_with_redacted_url():
    s, _ = _s([("subframe", "https://ads.example/pixel.html?uid=SECRET&t=1"), ("joblist", load_fixture("api/page1_ok.json"))])
    r = _search(s)
    assert r.kind == "success" and r.refused_subframes == 1
    assert r.notes == ("sub:unknown:https://ads.example/pixel.html?[t,uid]",)
    assert "SECRET" not in "".join(r.notes)

def test_security_page_in_a_subframe_still_stops_the_action():
    s, _ = _s([("subframe", "https://www.zhipin.com/web/common/security-check.html"),
               ("joblist", load_fixture("api/page1_ok.json"))])
    r = _search(s)
    assert (r.kind, r.reason) == ("blocked", "risk_redirect") and r.refused_subframes == 0

def test_main_document_redirect_with_extra_query_is_accepted():
    target = SEARCH + "&ka=search_list_1"
    s, t = _s([("redirect", target), ("joblist", load_fixture("api/page1_ok.json"))])
    r = _search(s)
    assert r.kind == "success" and t.documents_sent[-1] == target and r.refused_subframes == 0

def test_main_document_that_lands_on_another_site_page_fails_on_the_landing_check():
    """导航期间放行同站主文档，但最终地址必须落回期望页；停在站内别的页面按落点不符失败。"""
    s, t = _s([("redirect", "https://www.zhipin.com/web/geek/recommend?ka=x"),
               ("joblist", load_fixture("api/page1_ok.json"))])
    r = _search(s)
    assert (r.kind, r.reason) == ("unknown", "document_mismatch")
    assert t.documents_sent[-1] == "https://www.zhipin.com/web/geek/recommend?ka=x"
    assert r.notes == ("landing:https://www.zhipin.com/web/geek/recommend?[ka]",)

def test_renamed_list_page_reached_by_redirect_is_the_same_page():
    """平台把列表页路径从 job 改成 jobs：这一次导航内部跳过去，落点复核照样过，捕获照常认领。"""
    plural = SEARCH.replace("/web/geek/job?", "/web/geek/jobs?")
    s, t = _s([("redirect", plural), ("joblist", load_fixture("api/page1_ok.json"))])
    r = _search(s)
    assert (r.kind, r.reason) == ("success", "ok")
    assert t.documents_sent[-1] == plural and r.notes == ()

def test_next_page_after_the_list_page_was_renamed_still_matches():
    """翻页前的落点复核也认两种拼法：页面在第一页之后把地址换成复数路径，翻页照常。"""
    plural = SEARCH.replace("/web/geek/job?", "/web/geek/jobs?")
    s, t = _s([("joblist", load_fixture("api/page1_ok.json")), ("same_doc", plural),
               ("joblist", load_fixture("api/page2_ok.json"))])
    assert _search(s).kind == "success"
    r = s.next_page(2)
    assert (r.kind, r.reason) == ("success", "ok") and t.scrolls == 1

def test_notes_are_capped_and_reset_between_actions():
    from where_my_job.adapter.session import MAX_DOCUMENT_NOTES
    script = [("subframe", f"https://ads{i}.example/p.html") for i in range(MAX_DOCUMENT_NOTES + 3)]
    s, _ = _s(script + [("joblist", load_fixture("api/page1_ok.json")), ("joblist", load_fixture("api/page2_ok.json"))])
    first = _search(s)
    assert len(first.notes) == MAX_DOCUMENT_NOTES and first.refused_subframes == MAX_DOCUMENT_NOTES + 3
    second = s.next_page(2)
    assert second.kind == "success" and second.notes == () and second.refused_subframes == 0

HANDSHAKE = ("https://www.zhipin.com/web/passport/zp/security.html?appName=zhipin&callbackUrl=%2Fweb%2Fgeek%2Fjob"
             "&code=SYNCODE&name=zp&seed=SYNSEED&ts=1789516920")

def test_platform_handshake_hop_then_back_to_search_succeeds():
    """实测链路：平台在导航里插一跳再跳回搜索页，普通浏览器会自行跟随。"""
    s, t = _s([("redirect", HANDSHAKE), ("redirect", SEARCH), ("joblist", load_fixture("api/page1_ok.json"))])
    r = _search(s)
    assert (r.kind, r.reason) == ("success", "ok")
    assert t.documents_sent == [SEARCH, HANDSHAKE, SEARCH] and r.notes == ()

def test_stuck_on_the_handshake_page_is_treated_as_risk():
    s, _ = _s([("redirect", HANDSHAKE), ("joblist", load_fixture("api/page1_ok.json"))])
    r = _search(s)
    assert (r.kind, r.reason) == ("blocked", "handshake_not_finished")

def test_detail_page_stuck_on_the_handshake_page_is_treated_as_risk():
    s, _ = _s([("redirect", HANDSHAKE), ("page", load_fixture("pages/job_detail_ok.json"))])
    d = s.open_job_detail("SYN0101aaaa")
    assert (d.kind, d.reason) == ("blocked", "handshake_not_finished")

def test_new_main_document_during_scroll_is_not_used():
    """翻页期间页面换了主文档：拦截已关，文档会加载，但落点复核不过——停在握手页即判风控。"""
    s, _ = _s([("joblist", load_fixture("api/page1_ok.json")), ("new_document", HANDSHAKE),
               ("joblist", load_fixture("api/page2_ok.json"))])
    _search(s)
    r = s.next_page(2)
    assert (r.kind, r.reason) == ("blocked", "handshake_not_finished")

LOGIN_PAGE = "https://www.zhipin.com/web/user/?ka=header-login"

def test_timeout_after_the_page_switched_to_the_login_view_is_unauthenticated():
    """实测链路：登录态失效时平台不换文档，只把地址改成登录页并挡住列表。
    必须说未登录，而不是笼统的捕获失败——后者会让 agent 建议重试，而正确处置是重新登录。"""
    s, _ = _s([("same_doc", LOGIN_PAGE), ("timeout",)])
    r = _search(s)
    assert (r.kind, r.reason) == ("unauthenticated", "login_page")
    assert r.notes == ("landing:https://www.zhipin.com/web/user/?[ka]",)

def test_main_document_jump_to_the_login_page_is_still_a_login_redirect():
    """文档级跳到登录页由 Document 策略拦下，判定与原先一致，本计划不改这条路径。"""
    s, _ = _s([("redirect", LOGIN_PAGE), ("joblist", load_fixture("api/page1_ok.json"))])
    r = _search(s)
    assert (r.kind, r.reason) == ("unauthenticated", "login_redirect")

def test_timeout_on_the_expected_page_stays_capture_timeout():
    """真的只是没等到响应：落点仍是期望页，判定与原先一致，不得改判成未登录。"""
    s, _ = _s([("timeout",)])
    r = _search(s)
    assert (r.kind, r.reason) == ("unknown", "capture_timeout")
    assert r.notes == ("landing:https://www.zhipin.com/web/geek/job?[city,experience,page,query]",)

def test_timeout_after_switching_to_a_verification_page_is_risk():
    s, _ = _s([("same_doc", "https://www.zhipin.com/web/common/security-check.html?from=x"), ("timeout",)])
    r = _search(s)
    assert (r.kind, r.reason) == ("blocked", "risk_page")

def test_post_navigation_handshake_round_trip_is_followed_and_rebound():
    """刚扫码登录后平台在导航提交之后发起令牌握手往返：拦截此时已关，往返照常走完，回到期望页后重新绑定。"""
    s, t = _s([("hop", HANDSHAKE), ("hop", SEARCH), ("joblist", load_fixture("api/page1_ok.json"))])
    r = _search(s)
    assert (r.kind, r.reason) == ("success", "ok") and r.refused_subframes == 0
    assert r.notes == ("saw:https://www.zhipin.com/web/passport/zp/security.html?[appName,callbackUrl,code,name,seed,ts]",)
    assert t.guard is False                         # 列表页提交之后拦截确实关掉了

def test_rebound_action_still_supports_the_next_page():
    """重新绑定要落到本次动作上，否则翻页会拿着旧 loader 全部丢弃。"""
    s, _ = _s([("hop", HANDSHAKE), ("hop", SEARCH), ("joblist", load_fixture("api/page1_ok.json")),
               ("joblist", load_fixture("api/page2_ok.json"))])
    assert _search(s).kind == "success"
    assert s.next_page(2).kind == "success"

def test_page_that_stays_on_the_handshake_page_is_still_risk():
    """不拦不等于接受：停在握手家族页仍判风控，退出 3 与冷却一个字不改。"""
    s, _ = _s([("hop", HANDSHAKE), ("timeout",)])
    r = _search(s)
    assert (r.kind, r.reason) == ("blocked", "handshake_not_finished")

def test_page_that_wanders_to_another_site_page_is_not_used():
    """页面自己跳到站内别的页面：不再被拦，但落点复核不过，任何响应都不会被认领。"""
    s, _ = _s([("hop", "https://www.zhipin.com/web/geek/recommend?ka=x"), ("timeout",)])
    r = _search(s)
    assert (r.kind, r.reason) == ("unknown", "capture_timeout")
    assert "saw:https://www.zhipin.com/web/geek/recommend?[ka]" in r.notes
    assert any(n.startswith("landing:") for n in r.notes)

def test_page_that_switches_to_the_verify_or_login_page_is_classified_by_landing():
    """验证页与登录页不再靠拦截识别，靠落点分类识别；结论不变：风控与未登录。"""
    s, _ = _s([("hop", VERIFY_PAGE), ("timeout",)])
    r = _search(s)
    assert (r.kind, r.reason) == ("blocked", "risk_page")
    s2, _ = _s([("hop", LOGIN_PAGE), ("timeout",)])
    r2 = _search(s2)
    assert (r2.kind, r2.reason) == ("unauthenticated", "login_page")

VERIFY_PAGE = "https://www.zhipin.com/web/passport/zp/verify.html?scene=1"
