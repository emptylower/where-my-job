from dataclasses import replace
import pytest
from where_my_job.adapter.transport import (ActionExpectation, Captured, request_matches, match_failure,
                                            parameters_verified, bind_navigation_result)

EXP = ActionExpectation(action_id="a1", session_id="S", frame_id="F", loader_id="L1", keyword="AI产品经理",
                        city_code="101220100", page=2, canonical_filters={"experience": "101"}, started_sequence=10)
URL = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?query=AI%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86&city=101220100&page=2&experience=101&scene=1"

def _cap(**kw):
    base = dict(body="{}", http_status=200, request_id="r", url=URL, session_id="S", frame_id="F", loader_id="L1", request_sequence=11)
    base.update(kw)
    return Captured(**base)

def test_matching_capture():
    assert request_matches(EXP, _cap()) is True

@pytest.mark.parametrize("kw,code", [
    ({"session_id": "S2"}, "other_session"), ({"frame_id": "F2"}, "other_document"),
    ({"loader_id": "L0"}, "other_document"), ({"request_sequence": 10}, "before_action"),
    ({"url": URL.replace("https://", "http://")}, "other_endpoint"),
    ({"url": URL.replace("www.zhipin.com", "evil.example")}, "other_endpoint"),
    ({"url": URL.replace("www.zhipin.com", "www.zhipin.com:8443")}, "other_endpoint"),
    ({"url": URL.replace("joblist.json", "other.json")}, "other_endpoint"),
    ({"url": URL.replace("page=2", "page=999")}, "other_parameters"),
    ({"url": URL.replace("city=101220100", "city=101010100")}, "other_parameters"),
    ({"url": URL.replace("experience=101", "experience=104")}, "other_parameters"),
    ({"url": URL + "#frag"}, "other_endpoint"),
    ({"url": "https://u:p" + "@" + "www.zhipin.com/wapi/zpgeek/search/joblist.json"}, "other_endpoint"),
])
def test_non_matching(kw, code):
    assert request_matches(EXP, _cap(**kw)) is False
    assert match_failure(EXP, _cap(**kw)) == code

def test_matching_capture_has_no_failure_code():
    assert match_failure(EXP, _cap()) is None

def test_unbound_expectation_never_matches():
    assert request_matches(replace(EXP, loader_id=None), _cap()) is False
    assert match_failure(replace(EXP, loader_id=None), _cap()) == "unbound_action"

def test_bind_navigation_result():
    unbound = replace(EXP, loader_id=None)
    assert bind_navigation_result(unbound, {"id": 1, "result": {"frameId": "F", "loaderId": "L9"}}).loader_id == "L9"
    for bad in ({"error": {"message": "x"}}, {"result": {"frameId": "F", "loaderId": ""}},
                {"result": {"frameId": "F", "loaderId": "L", "errorText": "net::ERR"}},
                {"result": {"frameId": "OTHER", "loaderId": "L"}}, {"result": {"frameId": "F", "loaderId": "L", "isDownload": True}}):
        with pytest.raises(ValueError):
            bind_navigation_result(unbound, bad)
    with pytest.raises(ValueError):
        bind_navigation_result(EXP, {"result": {"frameId": "F", "loaderId": "L9"}})

def test_parameter_mismatch_names_only_keys_and_kinds():
    """逐项判定只回参数名与不符类型，不回参数值；查询串本身解析不了时不臆断。"""
    from where_my_job.adapter.transport import parameter_mismatch
    assert parameter_mismatch(EXP, _cap()) == ()
    assert parameter_mismatch(EXP, _cap(url=URL.replace("page=2", "page=999"))) == ("page=differs",)
    assert parameter_mismatch(EXP, _cap(url=URL.replace("&experience=101", ""))) == ("experience=missing",)
    assert parameter_mismatch(EXP, _cap(url=URL + "&page=2")) == ("page=duplicated",)
    assert parameter_mismatch(EXP, _cap(url="https://www.zhipin.com/wapi/zpgeek/search/joblist.json?%%%")) == ()

def test_response_without_any_search_parameters_is_accepted():
    """平台把搜索条件从接口地址上移走之后，地址里只剩防缓存参数：这条响应仍属于本次动作。"""
    bare = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?_=1789554458415"
    assert match_failure(EXP, _cap(url=bare)) is None
    assert request_matches(EXP, _cap(url=bare)) is True
    assert parameters_verified(EXP, _cap(url=bare)) is False

def test_partially_present_parameters_must_still_agree():
    """带了就必须一致：同一文档里翻错页的响应仍然要被挡住；漏带的那些不再单独构成不符。"""
    without_query = URL.replace("query=AI%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86&", "")
    assert match_failure(EXP, _cap(url=without_query)) is None
    assert parameters_verified(EXP, _cap(url=without_query)) is True
    assert match_failure(EXP, _cap(url=without_query.replace("page=2", "page=9"))) == "other_parameters"
    assert parameters_verified(EXP, _cap(url="https://www.zhipin.com/wapi/zpgeek/search/joblist.json?%%%")) is False
