"""开工前的空白页预检：只读 /json/list，不建立 CDP 会话，不占动作额度。"""
import pytest
from tests.helpers.fake_inspector import FakeInspector
from where_my_job.errors import EnvError
from where_my_job.launcher.chrome import CHROME_PATH, ChromeLauncher

def _launcher(wmj_home, targets):
    insp = FakeInspector()
    lch = ChromeLauncher(wmj_home, inspector=insp, exists=lambda p: True)
    v = lch.start()
    insp.targets = targets
    return lch, v, insp

def test_only_blank_pages_pass(wmj_home):
    lch, v, insp = _launcher(wmj_home, [{"type": "page", "url": "about:blank", "id": "T0"},
                                        {"type": "page", "url": "chrome://new-tab-page/", "id": "T1"}])
    lch.blank_check(v)
    assert ("fetch_targets", 9222) in insp.calls

def test_user_opened_page_is_refused_with_redacted_url(wmj_home):
    lch, v, _ = _launcher(wmj_home, [{"type": "page", "url": "about:blank", "id": "T0"},
                                     {"type": "page", "url": "https://www.zhipin.com/web/geek/job?query=x&lid=SECRET", "id": "T9"}])
    with pytest.raises(EnvError) as ei:
        lch.blank_check(v)
    assert ei.value.code == "BROWSER_NOT_BLANK"
    assert ei.value.data["browser"]["open_pages"] == ["https://www.zhipin.com/web/geek/job?[lid,query]"]
    assert "SECRET" not in str(ei.value.data)

def test_recorded_login_tab_is_allowed_by_its_json_list_id(wmj_home):
    """/json/list 的标识字段是 id，不是 targetId；认错字段会把正在进行的登录挡掉。"""
    lch, v, _ = _launcher(wmj_home, [{"type": "page", "url": "https://www.zhipin.com/web/user/", "id": "T-login"}])
    lch.blank_check(v, allow_target_id="T-login")
    with pytest.raises(EnvError):
        lch.blank_check(v, allow_target_id="T-other")

def test_non_page_targets_are_ignored(wmj_home):
    lch, v, _ = _launcher(wmj_home, [{"type": "service_worker", "url": "https://www.zhipin.com/sw.js", "id": "W1"},
                                     {"type": "background_page", "url": "chrome-extension://abc/x.html", "id": "B1"}])
    lch.blank_check(v)

def test_unreadable_target_list_does_not_block(wmj_home):
    """取不到清单时不拦：由 CdpTransport 建会话时兜底，宁可多花一次动作也不误拒。"""
    insp = FakeInspector()
    lch = ChromeLauncher(wmj_home, inspector=insp, exists=lambda p: True)
    v = lch.start()
    insp.version = None
    lch.blank_check(v)

def test_blank_check_requires_a_verified_browser_on_the_same_port(wmj_home):
    from dataclasses import replace
    lch, v, _ = _launcher(wmj_home, [{"type": "page", "url": "about:blank", "id": "T0"}])
    other = replace(v, state=replace(v.state, port=9333))
    with pytest.raises(EnvError) as ei:
        lch.blank_check(other)
    assert ei.value.code == "PROFILE_NOT_OWNED"
    assert lch.chrome_path == CHROME_PATH
