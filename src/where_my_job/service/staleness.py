# src/where_my_job/service/staleness.py
"""命令级版本检查：当前 match 批次使用的 scoring 文件与画像版本是否仍一致；冻结输入提示。
job list/show、panel、status、match 共用。"""
from __future__ import annotations
import json
from pathlib import Path
from ..config.loader import load_json_file
from ..errors import WmjError
from ..ids import sha256_json
from ..store import matches
from .context import Context

FROZEN_NOTICE = "冻结历史输入：legacy-20260914（不代表岗位当前条件）"

def add_warning(ctx: Context, message: str) -> None:
    if message not in ctx.warnings:
        ctx.warnings.append(message)

def version_warnings(ctx: Context) -> dict | None:
    """返回当前批次 config（无批次为 None），并把过期原因追加到 ctx.warnings。"""
    cur = matches.current_run(ctx.conn)
    if not cur:
        return None
    cfg = json.loads(cur["config_json"])
    if cfg.get("input_selection") == "legacy-20260914":
        add_warning(ctx, FROZEN_NOTICE)
    scoring_path = cfg.get("scoring_path")
    if scoring_path:
        try:
            now = load_json_file(Path(scoring_path), "scoring")
        except WmjError:
            add_warning(ctx, f"当前匹配使用的 scoring 文件缺失、不可读或校验失败：{scoring_path}；匹配结果可能过期")
            now = None
        if now is not None and sha256_json(now) != cfg.get("scoring_hash"):
            add_warning(ctx, "scoring 配置已变化，当前匹配结果可能过期；运行 match 重新计算")
    bound = ctx.conn.execute("select wmj_profile_revision()").fetchone()[0]
    run_profile = cfg.get("profile_revision")
    if bound is None:
        add_warning(ctx, "未绑定有效画像版本，匹配结果显示为过期")
    elif bound != run_profile:
        add_warning(ctx, f"画像版本已变化（{run_profile} → {bound}），匹配结果显示为过期")
    return cfg
