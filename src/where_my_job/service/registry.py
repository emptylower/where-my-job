"""子命令注册表。每个 service 模块暴露 register(sub, set_handler)，在这里按顺序列出。"""
from __future__ import annotations
import argparse

def _set(parser: argparse.ArgumentParser, qualified: str, handler) -> None:
    parser.set_defaults(handler=handler, qualified_command=qualified)

def register_all(sub: argparse._SubParsersAction) -> None:
    from . import version_cmd, init, status, import_, jobs, data, validate_cmd, match, attrs, panel
    from . import streams, events
    from . import evidence; evidence.register(sub, _set)
    from . import deepdive; deepdive.register(sub, _set)
    from . import scan; scan.register(sub, _set)
    from . import browser; browser.register(sub, _set)
    from . import login; login.register(sub, _set)
    from . import reports; reports.register(sub, _set)
    version_cmd.register(sub, _set)
    init.register(sub, _set)
    status.register(sub, _set)
    import_.register(sub, _set)
    jobs.register(sub, _set)
    data.register(sub, _set)
    validate_cmd.register(sub, _set)
    match.register(sub, _set)
    attrs.register(sub, _set)
    panel.register(sub, _set)
    streams.register(sub, _set)
    events.register(sub, _set)
