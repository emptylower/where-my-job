import base64
import pytest
from where_my_job.adapter.cdp import CdpTransport
from where_my_job.browser_pages import BLANK_URLS
from where_my_job.adapter.transport import DocumentDecision
from where_my_job.errors import EnvError
from tests.helpers.fake_ws import FakeWS, Ticker

def _responder(targets=None, events=None):
    targets = targets if targets is not None else [{"type": "page", "url": "about:blank", "targetId": "T0"}]
    events = events or {}
    def respond(msg):
        m, mid = msg.get("method"), msg.get("id")
        out = list(events.pop(m, []))
        if m == "Target.getTargets":
            out.append({"id": mid, "result": {"targetInfos": targets}})
        elif m == "Target.createTarget":
            out.append({"id": mid, "result": {"targetId": "T1"}})
        elif m == "Target.attachToTarget":
            out.append({"id": mid, "result": {"sessionId": "S1"}})
        elif m == "Page.getFrameTree":
            out.append({"id": mid, "result": {"frameTree": {"frame": {"id": "F1", "loaderId": "L0", "url": "about:blank"}}}})
        elif m == "Page.navigate":
            out.append({"id": mid, "result": {"frameId": "F1", "loaderId": "L1"}})
            out.append({"method": "Page.frameNavigated", "sessionId": "S1",
                        "params": {"frame": {"id": "F1", "loaderId": "L1", "url": msg["params"]["url"]}}})
        elif m == "Network.getResponseBody":
            if msg["params"]["requestId"] == "bad":
                out.append({"id": mid, "error": {"message": "No resource"}})
            else:
                out.append({"id": mid, "result": {"body": base64.b64encode(b'{"code":0}').decode(), "base64Encoded": True}})
        elif mid is not None:
            out.append({"id": mid, "result": {}})
        return out
    return respond

def _open(ws):
    captured = {}
    def connect(url, **kw):
        captured.update(kw, url=url); return ws
    t = CdpTransport.open("ws://127.0.0.1:9222/devtools/browser/abc", connect=connect, monotonic=Ticker())
    return t, captured

def test_open_uses_suppressed_origin_no_proxy_and_no_interception_yet():
    """建会话时不拦截：拦截只在本工具自己导航与登录流程期间开着。"""
    ws = FakeWS(_responder())
    t, kw = _open(ws)
    assert kw["suppress_origin"] is True and set(kw["http_no_proxy"]) >= {"127.0.0.1", "::1"}
    assert not [m for m in ws.sent if m["method"] == "Fetch.enable"]
    assert not [m for m in ws.sent if m["method"] in ("Page.addScriptToEvaluateOnNewDocument", "Runtime.addBinding")]
    assert t.session_id == "S1" and t.frame_id == "F1"

def test_navigation_turns_the_guard_on_and_it_can_be_turned_off_once():
    ws = FakeWS(_responder())
    t, _ = _open(ws)
    t.navigate("https://www.zhipin.com/web/geek/job?query=x")
    fetch = [m for m in ws.sent if m["method"] == "Fetch.enable"]
    assert len(fetch) == 1
    assert fetch[0]["params"] == {"patterns": [{"resourceType": "Document", "requestStage": "Request"}]}
    t.set_document_guard(False)
    t.set_document_guard(False)                     # 幂等：状态没变就不发命令
    assert len([m for m in ws.sent if m["method"] == "Fetch.disable"]) == 1

def test_main_frame_navigations_are_observable():
    """拦截关掉之后，页面自己的跳转靠这条观察通道可见。"""
    ws = FakeWS(_responder())
    t, _ = _open(ws)
    ws.push({"method": "Page.frameNavigated", "sessionId": "S1",
             "params": {"frame": {"id": "F1", "url": "https://www.zhipin.com/web/passport/zp/security.html?code=x",
                                  "loaderId": "L9"}}})
    t.idle(1.0)
    assert t.take_navigations() == ["https://www.zhipin.com/web/passport/zp/security.html?code=x"]
    assert t.take_navigations() == []

def test_restored_or_user_opened_tabs_refuse_before_creating_target():
    ws = FakeWS(_responder(targets=[{"type": "page", "url": "https://www.zhipin.com/web/geek/job?query=x", "targetId": "T9"}]))
    with pytest.raises(EnvError) as ei:
        _open(ws)
    assert ei.value.code == "BROWSER_NOT_BLANK" and not [m for m in ws.sent if m["method"] == "Target.createTarget"]
    assert ei.value.data["browser"]["open_pages"] == ["https://www.zhipin.com/web/geek/job?[query]"]
    assert "browser stop" in ei.value.data["browser"]["next_step"]
    assert ws.closed and "about:blank" in BLANK_URLS

def test_document_interception_continue_unmodified_or_fail_blocked_by_client():
    paused = lambda rid, url, frame="F1": {"method": "Fetch.requestPaused", "sessionId": "S1",
        "params": {"requestId": rid, "resourceType": "Document", "frameId": frame, "request": {"url": url}}}
    ws = FakeWS(_responder())
    t, _ = _open(ws)
    t.set_document_policy(lambda url, main: DocumentDecision(url.endswith("/ok.html"), "ok" if url.endswith("/ok.html") else "blocked"))
    ws.responder = _responder(events={"Page.navigate": [paused("p1", "https://www.zhipin.com/job_detail/ok.html"),
                                                        paused("p2", "https://www.zhipin.com/web/common/security-check.html")]})
    t.navigate("https://www.zhipin.com/job_detail/ok.html")
    cont = [m for m in ws.sent if m["method"] == "Fetch.continueRequest"]
    fail = [m for m in ws.sent if m["method"] == "Fetch.failRequest"]
    assert cont[0]["params"] == {"requestId": "p1"}
    assert fail[0]["params"] == {"requestId": "p2", "errorReason": "BlockedByClient"}
    assert t.take_blocked_documents() == [("https://www.zhipin.com/web/common/security-check.html", "blocked", True)]

def test_policy_is_fail_closed_before_session_sets_it():
    ws = FakeWS(_responder())
    t, _ = _open(ws)
    ws.responder = _responder(events={"Page.navigate": [{"method": "Fetch.requestPaused", "sessionId": "S1",
        "params": {"requestId": "p1", "resourceType": "Document", "frameId": "F1", "request": {"url": "https://www.zhipin.com/"}}}]})
    t.navigate("https://www.zhipin.com/")
    assert [m for m in ws.sent if m["method"] == "Fetch.failRequest"]

def test_captures_real_status_body_and_body_failure():
    ws = FakeWS(_responder())
    t, _ = _open(ws)
    url = "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?query=a&city=1&page=1"
    for rid, status in (("good", 403), ("bad", 200)):
        ws.push({"method": "Network.requestWillBeSent", "sessionId": "S1",
                 "params": {"requestId": rid, "frameId": "F1", "loaderId": "L1", "request": {"url": url}}})
        ws.push({"method": "Network.responseReceived", "sessionId": "S1", "params": {"requestId": rid, "response": {"status": status}}})
        ws.push({"method": "Network.loadingFinished", "sessionId": "S1", "params": {"requestId": rid}})
    caps = t.captures(5.0)
    by = {c.request_id: c for c in caps}
    assert by["good"].http_status == 403 and by["good"].body == '{"code":0}' and by["good"].loader_id == "L1"
    assert by["bad"].body is None and by["bad"].error_text == "body_unavailable"
    assert by["good"].request_sequence < by["bad"].request_sequence

def test_captures_timeout_returns_empty():
    ws = FakeWS(_responder())
    t, _ = _open(ws)
    assert t.captures(1.0) == []

def _with_screenshot(reply):
    base = _responder()
    def respond(msg):
        if msg.get("method") == "Page.captureScreenshot":
            return [dict(reply, id=msg["id"])]
        return base(msg)
    return respond

def test_screenshot_uses_own_session_and_decodes_png_bytes():
    ws = FakeWS(_with_screenshot({"result": {"data": base64.b64encode(b"\x89PNG-synthetic").decode()}}))
    t, _ = _open(ws)
    assert t.screenshot() == b"\x89PNG-synthetic"
    sent = [m for m in ws.sent if m["method"] == "Page.captureScreenshot"]
    assert sent[0]["sessionId"] == "S1" and sent[0]["params"] == {"format": "png"}

def test_screenshot_error_returns_none():
    t, _ = _open(FakeWS(_with_screenshot({"error": {"message": "Not attached"}})))
    assert t.screenshot() is None

def test_idle_keeps_answering_paused_documents():
    ws = FakeWS(_responder())
    t, _ = _open(ws)
    t.set_document_policy(lambda url, main: DocumentDecision(False, "blocked"))
    ws.push({"method": "Fetch.requestPaused", "sessionId": "S1",
             "params": {"requestId": "r9", "resourceType": "Document", "frameId": "F1",
                        "request": {"url": "https://www.zhipin.com/web/common/security-check.html"}}})
    t.idle(1.0)
    assert [m["params"]["requestId"] for m in ws.sent if m["method"] == "Fetch.failRequest"] == ["r9"]
    assert t.take_blocked_documents() == [("https://www.zhipin.com/web/common/security-check.html", "blocked", True)]

def test_attach_to_recorded_login_tab_without_creating_target():
    targets = [{"type": "page", "url": "about:blank", "targetId": "T0"},
               {"type": "page", "url": "https://www.zhipin.com/web/user/", "targetId": "T-login"}]
    ws = FakeWS(_responder(targets=targets))
    t = CdpTransport.open("ws://127.0.0.1:9222/devtools/browser/abc", target_id="T-login",
                          connect=lambda url, **kw: ws, monotonic=Ticker())
    assert t.target_id == "T-login" and t.session_id == "S1"
    assert not [m for m in ws.sent if m["method"] == "Target.createTarget"]
    attach = [m for m in ws.sent if m["method"] == "Target.attachToTarget"][0]
    assert attach["params"] == {"targetId": "T-login", "flatten": True}

@pytest.mark.parametrize("targets,code", [
    ([{"type": "page", "url": "about:blank", "targetId": "T0"}], "LOGIN_NOT_STARTED"),
    ([{"type": "page", "url": "https://www.zhipin.com/web/user/", "targetId": "T-login"},
      {"type": "page", "url": "https://example.invalid/", "targetId": "T-other"}], "BROWSER_NOT_BLANK"),
])
def test_attach_refuses_missing_tab_and_foreign_tabs(targets, code):
    ws = FakeWS(_responder(targets=targets))
    with pytest.raises(EnvError) as ei:
        CdpTransport.open("ws://127.0.0.1:9222/devtools/browser/abc", target_id="T-login",
                          connect=lambda url, **kw: ws, monotonic=Ticker())
    assert ei.value.code == code and ws.closed

def test_detach_keeps_tab_open():
    ws = FakeWS(_responder())
    t, _ = _open(ws)
    t.detach()
    assert ws.closed
    assert [m for m in ws.sent if m["method"] == "Fetch.disable"]
    assert not [m for m in ws.sent if m["method"] == "Target.closeTarget"]

def test_blocked_records_tell_main_document_from_subframe():
    paused = lambda rid, url, frame: {"method": "Fetch.requestPaused", "sessionId": "S1",
        "params": {"requestId": rid, "resourceType": "Document", "frameId": frame, "request": {"url": url}}}
    ws = FakeWS(_responder())
    t, _ = _open(ws)
    t.set_document_policy(lambda url, main: DocumentDecision(False, "blocked" if main else "unknown"))
    ws.responder = _responder(events={"Page.navigate": [
        paused("m1", "https://www.zhipin.com/web/common/security-check.html", "F1"),
        paused("s1", "https://ads.example/pixel.html", "F-sub")]})
    t.navigate("https://www.zhipin.com/web/geek/job?query=x")
    assert t.take_blocked_documents() == [("https://www.zhipin.com/web/common/security-check.html", "blocked", True),
                                          ("https://ads.example/pixel.html", "unknown", False)]
    assert [m["params"]["requestId"] for m in ws.sent if m["method"] == "Fetch.failRequest"] == ["m1", "s1"]

def test_same_document_navigation_updates_the_reported_url():
    """页面用 pushState 换地址时不产生新文档：报告的地址必须跟着变，
    否则落点判定读到的永远是旧地址，登录层挡住列表这种情况就看不出来。"""
    ws = FakeWS(_responder())
    t, _ = _open(ws)
    t.navigate("https://www.zhipin.com/web/geek/job?query=x")
    assert t.document()["url"] == "https://www.zhipin.com/web/geek/job?query=x"
    ws.push({"method": "Page.navigatedWithinDocument", "sessionId": "S1",
             "params": {"frameId": "F1", "url": "https://www.zhipin.com/web/user/"}})
    t.idle(1.0)
    doc = t.document()
    assert doc["url"] == "https://www.zhipin.com/web/user/"
    assert doc["frame_id"] == "F1" and doc["loader_id"] == "L1"

def test_same_document_navigation_of_another_frame_is_ignored():
    ws = FakeWS(_responder())
    t, _ = _open(ws)
    t.navigate("https://www.zhipin.com/web/geek/job?query=x")
    ws.push({"method": "Page.navigatedWithinDocument", "sessionId": "S1",
             "params": {"frameId": "F-sub", "url": "https://ads.example/x"}})
    t.idle(1.0)
    assert t.document()["url"] == "https://www.zhipin.com/web/geek/job?query=x"
