# src/where_my_job/service/profile_binding.py
"""把当前 profile.json 的 profile_revision 绑定到连接函数 wmj_profile_revision()。
读取或校验失败时绑定 None 并给出警告；查询继续可用，但匹配与报告不会显示为 current/complete。"""
from __future__ import annotations
from ..config.loader import load_json_file
from ..errors import WmjError
from ..paths import Layout
from ..store import db

def bind_current_profile(conn: db.Connection, lay: Layout, warnings: list[str]) -> str | None:
    path = lay.config("profile.json")
    if not path.exists():
        db.bind_profile_revision(conn, None)
        return None
    try:
        obj = load_json_file(path, "profile")
    except WmjError as e:
        message = f"profile.json 无法读取或校验失败（{e.code}）：匹配与报告将显示为过期"
        if message not in warnings:
            warnings.append(message)
        db.bind_profile_revision(conn, None)
        return None
    revision = obj.get("profile_revision") or None
    db.bind_profile_revision(conn, revision)
    return revision
