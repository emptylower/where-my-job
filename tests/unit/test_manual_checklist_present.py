# tests/unit/test_manual_checklist_present.py
import pathlib
P = pathlib.Path(__file__).resolve().parents[2] / "tests" / "manual" / "ONLINE_CHECKLIST.md"

def test_checklist_exists_and_declares_gates():
    t = P.read_text(encoding="utf-8")
    for must in ("不作为 CI", "发布门槛", "停止条件", "127.0.0.1", "记录模板", "RISK_DETECTED", "不主动制造风控",
                 "Fetch.enable", "BlockedByClient", "删除拦截", "空白重启", "异常退出", "about:blank", "保持 disabled"):
        assert must in t, must
