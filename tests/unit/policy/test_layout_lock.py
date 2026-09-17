import os, subprocess, sys, textwrap
import pytest
from where_my_job.paths import Layout
from where_my_job.errors import Blocked, EnvError
from where_my_job.policy.layout import checked_network_layout, profile_id_for
from where_my_job.policy.lock import BrowserLock, is_locked

def test_whole_home_alias_resolves_to_same_profile(wmj_home, tmp_path):
    alias = tmp_path / "home-alias"
    os.symlink(wmj_home.root, alias)
    a = checked_network_layout(Layout(alias))
    b = checked_network_layout(wmj_home)
    assert a.root == b.root and profile_id_for(a.browser_profile) == profile_id_for(b.browser_profile)
    assert len(profile_id_for(a.browser_profile)) == 16

@pytest.mark.parametrize("attr", ["browser_profile", "state"])
def test_linked_subdirectory_is_rejected(wmj_home, tmp_path, attr):
    target = getattr(wmj_home, attr)
    if target.exists():
        os.rename(target, tmp_path / "moved")
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir()
    os.symlink(elsewhere, target)
    with pytest.raises(EnvError) as ei:
        checked_network_layout(wmj_home)
    assert ei.value.code == "PROFILE_NOT_OWNED"

@pytest.mark.parametrize("attr", ["db_path", "lock_path"])
def test_linked_state_file_is_rejected(wmj_home, tmp_path, attr):
    target = getattr(wmj_home, attr)
    if target.exists():
        target.unlink()
    other = tmp_path / "other-file"; other.write_text("")
    os.symlink(other, target)
    with pytest.raises(EnvError) as ei:
        checked_network_layout(wmj_home)
    assert ei.value.code == "PROFILE_NOT_OWNED"

def test_layout_check_creates_nothing(tmp_path):
    fresh = Layout(tmp_path / "never-created")
    checked_network_layout(fresh)
    assert not (tmp_path / "never-created").exists()

def _holder(home: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import time
        from where_my_job.paths import Layout
        from where_my_job.policy.lock import BrowserLock
        with BrowserLock(Layout(__import__("pathlib").Path({home!r}))):
            print("held", flush=True); time.sleep(10)
    """)], stdout=subprocess.PIPE, text=True)

def test_second_process_through_home_alias_gets_resource_busy(wmj_home, tmp_path):
    alias = tmp_path / "alias"; os.symlink(wmj_home.root, alias)
    holder = _holder(str(wmj_home.root))
    assert holder.stdout.readline().strip() == "held"
    try:
        assert is_locked(Layout(alias)) is True
        with pytest.raises(Blocked) as ei:
            with BrowserLock(Layout(alias)):
                pass
        assert ei.value.code == "RESOURCE_BUSY" and "lock" not in ei.value.message
    finally:
        holder.kill(); holder.wait()

def test_lock_released_when_holder_dies(wmj_home):
    holder = _holder(str(wmj_home.root))
    holder.stdout.readline(); holder.kill(); holder.wait()
    with BrowserLock(wmj_home) as lock:
        assert lock.held
    assert not lock.held

def test_is_locked_does_not_create_lock_file(wmj_home):
    assert not wmj_home.lock_path.exists()
    assert is_locked(wmj_home) is False
    assert not wmj_home.lock_path.exists()
