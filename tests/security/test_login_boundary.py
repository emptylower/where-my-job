# tests/security/test_login_boundary.py
import pathlib
import pytest
from where_my_job.adapter import login

SRC = pathlib.Path(login.__file__).resolve().parents[1]

@pytest.mark.parametrize("url,allow,state", [
    ("https://www.zhipin.com/web/user/", True, "ok"),
    ("https://www.zhipin.com/web/user/?ka=header-login", True, "ok"),
    ("https://www.zhipin.com/web/geek/job-recommend", True, "ok"),
    ("https://www.zhipin.com/web/common/security-check.html", False, "blocked"),
    ("https://evil.example/web/user/", False, "unknown"),
    ("http://www.zhipin.com/web/user/", False, "unknown"),
    ("https://www.zhipin.com:8443/web/user/", False, "unknown"),
])
def test_login_document_policy(url, allow, state):
    for main in (True, False):
        decision = login.decide_document(url, main)
        assert (decision.allow, decision.state) == (allow, state)

def test_login_url_is_fixed_https_same_site():
    assert login.LOGIN_URL == "https://www.zhipin.com/web/user/"

def test_login_code_never_reads_cookies_or_makes_own_requests():
    banned = ("getCookies", "document.cookie", "Storage.", "Fetch.fulfillRequest", "fetch(", "XMLHttpRequest",
              "addScriptToEvaluateOnNewDocument", "Runtime.addBinding", "sendBeacon")
    for rel in ("adapter/login.py", "adapter/qr.py", "adapter/cdp.py", "service/login.py"):
        text = (SRC / rel).read_text(encoding="utf-8")
        for word in banned:
            assert word not in text, (rel, word)
