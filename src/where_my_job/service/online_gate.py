# src/where_my_job/service/online_gate.py
from __future__ import annotations
from .. import release
from ..config.loader import load_json_file
from ..errors import EnvError
from .context import Context

def _user_setting(ctx: Context) -> str | None:
    p = ctx.home.config("settings.json")
    if not p.exists():
        return None
    return load_json_file(p, "settings").get("online_adapter")

def require_online_enabled(ctx: Context) -> None:
    """只由 scan.run、非缓存 deepdive.run、browser.start_browser、browser.probe 在第一条业务语句调用。"""
    if release.ONLINE_ADAPTER_DEFAULT != "enabled":
        raise EnvError("ONLINE_DISABLED",
                       "本版本是禁用在线适配器的离线 beta（在线功能发布门槛未通过）。导入、匹配、面板、证据、报告、事件可用。")
    if _user_setting(ctx) == "disabled":
        raise EnvError("ONLINE_DISABLED", "settings.json 已将 online_adapter 设为 disabled。删除该项或改为 enabled 后重试。")
