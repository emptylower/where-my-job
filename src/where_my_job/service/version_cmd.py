# src/where_my_job/service/version_cmd.py
from __future__ import annotations
from .. import __version__, release

def register(sub, set_handler):
    p = sub.add_parser("version", help="输出版本与在线适配器的发布默认值")
    set_handler(p, "version", lambda ns, warnings: {"version": __version__,
                                                    "online_adapter_default": release.ONLINE_ADAPTER_DEFAULT})
