"""网络入口统一使用的规范布局。整个 WMJ_HOME 可以是别名；其下受保护子路径不得被链接到别处。
只依赖 paths/errors；不创建任何目录或文件。"""
from __future__ import annotations
import hashlib
from pathlib import Path
from ..errors import EnvError
from ..paths import Layout
from ..public_messages import public_message

def checked_network_layout(lay: Layout) -> Layout:
    canonical = Layout(lay.root.expanduser().resolve())
    guarded = (canonical.state, canonical.browser_profile, canonical.db_path, canonical.lock_path)
    for path in guarded:
        if path.resolve() != path:
            raise EnvError("PROFILE_NOT_OWNED", public_message("PROFILE_NOT_OWNED"))
    return canonical

def profile_id_for(canonical_profile: Path) -> str:
    """调用方必须传 checked_network_layout(...).browser_profile。"""
    return hashlib.sha256(str(canonical_profile).encode("utf-8")).hexdigest()[:16]
