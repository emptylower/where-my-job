import pytest
from tests.helpers.fake_transport import FakeTransport
from where_my_job.adapter.session import BrowserSession, NavigationRefused, ALLOWED_URL, classify_document_url

@pytest.mark.parametrize("url", [
    "https://www.zhipin.com/web/geek/job?query=a&city=101220100&page=1",
    "https://www.zhipin.com/job_detail/abc123DEF~_-.html",
    "https://www.zhipin.com/gongsi/abc123.html",
])
def test_allowed(url):
    assert ALLOWED_URL.fullmatch(url)

@pytest.mark.parametrize("url", [
    "http://www.zhipin.com/web/geek/job?query=a",
    "https://zhipin.com/job_detail/abc.html",
    "https://www.zhipin.com.evil.example/job_detail/abc.html",
    "https://www.zhipin.com/job_detail/abc.html?lid=x&securityId=y",
    "https://www.zhipin.com/web/user/",
    "javascript:alert(1)",
    "file:///etc/passwd",
])
def test_refused(url):
    assert not ALLOWED_URL.fullmatch(url)
    with pytest.raises(NavigationRefused):
        BrowserSession(FakeTransport([])).navigate_checked(url)

def test_imported_job_link_is_never_navigated_directly():
    link = "https://www.zhipin.com/job_detail/SYN0101aaaa.html?lid=SYN.lid.101&securityId=SYN-SECURITY-101"
    with pytest.raises(NavigationRefused):
        BrowserSession(FakeTransport([])).navigate_checked(link)

USERINFO_DOC = "https://user" + "@" + "www.zhipin.com/job_detail/A.html"   # 运行时拼接：源码不出现邮箱样式字面量（子计划 06 发行扫描）

@pytest.mark.parametrize("url,expected,state", [
    ("https://www.zhipin.com/job_detail/A.html", "https://www.zhipin.com/job_detail/A.html", "ok"),
    # 导航进行中放行同站主文档：平台会在链路里插自己的跳转；落点是否正确由 _doc_ok 复核
    ("https://www.zhipin.com/job_detail/B.html", "https://www.zhipin.com/job_detail/A.html", "ok"),
    ("https://www.zhipin.com/web/passport/zp/security.html?seed=x", "https://www.zhipin.com/job_detail/A.html", "ok"),
    ("https://www.zhipin.com/job_detail/B.html", None, "unknown"),          # 导航结束后不再接受新的主文档
    ("https://www.zhipin.com/web/user/?ka=x", "https://www.zhipin.com/job_detail/A.html", "unauthenticated"),
    ("https://www.zhipin.com/web/common/security-check.html", None, "blocked"),
    ("https://www.zhipin.com/web/passport/zp/verify.html", "https://www.zhipin.com/job_detail/A.html", "blocked"),
    ("https://evil.example/job_detail/A.html", "https://www.zhipin.com/job_detail/A.html", "unknown"),
    ("https://www.zhipin.com:8443/job_detail/A.html", "https://www.zhipin.com:8443/job_detail/A.html", "unknown"),
    (USERINFO_DOC, USERINFO_DOC, "unknown"),
    ("https://www.zhipin.com/job_detail/A.html#x", "https://www.zhipin.com/job_detail/A.html#x", "unknown"),
])
def test_classify_document_url(url, expected, state):
    assert classify_document_url(url, expected) == state

@pytest.mark.parametrize("url,expected,ok", [
    ("https://www.zhipin.com/web/geek/job?query=a&city=1&page=1&ka=x",
     "https://www.zhipin.com/web/geek/job?query=a&city=1&page=1", True),
    ("https://www.zhipin.com/web/geek/job?query=a", "https://www.zhipin.com/web/geek/job?query=a", True),
    ("https://evil.example/web/geek/job?query=a", "https://www.zhipin.com/web/geek/job?query=a", False),
    ("https://www.zhipin.com/web/user/?ka=x", "https://www.zhipin.com/web/geek/job?query=a", False),
    ("https://www.zhipin.com/web/geek/job?query=a", None, False),
])
def test_same_document_refuses_other_sites_and_other_pages(url, expected, ok):
    from where_my_job.adapter.session import same_document
    assert same_document(url, expected) is ok

def test_same_document_accepts_both_spellings_of_the_list_page_only():
    """平台把搜索列表页从 /web/geek/job 改名为 /web/geek/jobs：两种拼法互认，别的页面一概不认。"""
    from where_my_job.adapter.session import same_document
    singular = "https://www.zhipin.com/web/geek/job?query=a&city=1&page=1"
    plural = "https://www.zhipin.com/web/geek/jobs?query=a&city=1&page=1"
    assert same_document(plural, singular) is True
    assert same_document(singular, plural) is True
    assert same_document("https://www.zhipin.com/web/geek/recommend?query=a", singular) is False
    assert same_document("https://www.zhipin.com/job_detail/A.html", plural) is False
    assert same_document("https://evil.example/web/geek/jobs?query=a", singular) is False

def test_redact_url_keeps_parameter_names_not_values():
    from where_my_job.adapter.session import redact_url
    out = redact_url("https://www.zhipin.com/job_detail/A.html?lid=SECRETLID&securityId=SECRETID")
    assert out == "https://www.zhipin.com/job_detail/A.html?[lid,securityId]"
    assert "SECRETLID" not in out and "SECRETID" not in out
