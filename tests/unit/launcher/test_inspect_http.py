"""真实 Inspector 的 HTTP 探测：只连数值回环，不走环境代理，不跟随重定向。"""
import http.server, json, threading
import pytest
from where_my_job.launcher.inspect import Inspector

class _H(http.server.BaseHTTPRequestHandler):
    mode = "ok"
    def do_GET(self):
        if _H.mode == "redirect":
            self.send_response(302); self.send_header("Location", "http://127.0.0.1:1/json/version"); self.end_headers(); return
        if self.path == "/json/list":
            body = json.dumps([{"type": "page", "url": "about:blank", "id": "T0"}, "junk"]).encode()
        else:
            body = json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1:1/devtools/browser/x"}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass

@pytest.fixture
def server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    yield srv.server_address[1]
    srv.shutdown()

def test_fetch_ignores_env_proxy(server, monkeypatch):
    _H.mode = "ok"
    monkeypatch.setenv("http_proxy", "http://10.255.255.1:9"); monkeypatch.setenv("HTTP_PROXY", "http://10.255.255.1:9")
    assert Inspector().fetch_version(server)["webSocketDebuggerUrl"].startswith("ws://127.0.0.1")

def test_fetch_does_not_follow_redirect(server):
    _H.mode = "redirect"
    assert Inspector().fetch_version(server) is None

def test_fetch_targets_returns_only_dict_entries(server):
    _H.mode = "ok"
    assert Inspector().fetch_targets(server) == [{"type": "page", "url": "about:blank", "id": "T0"}]

def test_fetch_targets_does_not_follow_redirect(server):
    _H.mode = "redirect"
    assert Inspector().fetch_targets(server) is None
