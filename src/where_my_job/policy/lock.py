"""同一规范专用 profile 一个 OS 文件锁。启动、停止、在线动作共用。锁随进程退出释放；文件残留内容不代表持有。"""
from __future__ import annotations
import errno, fcntl, os
from ..errors import Blocked
from ..paths import Layout
from ..public_messages import public_message
from .layout import checked_network_layout, profile_id_for

class BrowserLock:
    def __init__(self, lay: Layout):
        self.lay = checked_network_layout(lay)
        self.path = self.lay.lock_path
        self.profile_id = profile_id_for(self.lay.browser_profile)
        self._fd: int | None = None
        self.held = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            if exc.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):
                raise Blocked("RESOURCE_BUSY", public_message("RESOURCE_BUSY"),
                              retry={"automatic": False, "not_before": None})
            raise
        os.ftruncate(fd, 0)
        os.write(fd, f"{self.profile_id}\n{os.getpid()}\n".encode("ascii"))
        os.fchmod(fd, 0o600)
        self._fd, self.held = fd, True
        return self

    def __exit__(self, *exc):
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
        self._fd, self.held = None, False
        return False

def is_locked(lay: Layout) -> bool:
    """只读探测（status 用）：锁文件不存在即未持有；不创建文件。"""
    path = checked_network_layout(lay).lock_path
    if not path.exists():
        return False
    fd = os.open(path, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)
