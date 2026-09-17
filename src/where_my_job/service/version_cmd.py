# src/where_my_job/service/version_cmd.py
from __future__ import annotations
import hashlib, pathlib
from .. import __version__, release

_HASHED_SUFFIXES = (".py", ".json", ".sql", ".html", ".js")
_SKIP_DIRS = ("__pycache__",)

def build_id() -> str:
    """装好的这一份包自身的指纹。

    版本号常年是 0.1.0，新旧构建长得一模一样；而 `uv tool install` 会复用构建缓存，
    静默把旧代码装上去（本项目已经栽过三次：面板模板、城市码、登录字段）。
    把包内源码算成一个短哈希，和 `uv run --project <仓库> where-my-job version` 的
    build_id 一比就知道装的是不是那份仓库——原来 SKILL.md 要求"确认版本来自你正在用的
    那份仓库"，但没有任何可比的东西，那条指令没法执行。

    只哈希包内文件、只用相对路径，所以装在哪儿不影响结果。"""
    root = pathlib.Path(__file__).resolve().parent.parent
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix not in _HASHED_SUFFIXES:
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        h.update(str(p.relative_to(root)).encode("utf-8"))
        h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()[:12]

def register(sub, set_handler):
    p = sub.add_parser("version", help="输出版本、在线适配器发布默认值，以及这份构建的指纹")
    set_handler(p, "version", lambda ns, warnings: {"version": __version__,
                                                    "build_id": build_id(),
                                                    "online_adapter_default": release.ONLINE_ADAPTER_DEFAULT})
