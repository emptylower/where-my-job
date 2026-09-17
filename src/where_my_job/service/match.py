# src/where_my_job/service/match.py
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
from ..clock import iso_utc, parse_iso
from ..config.loader import load_json_file
from ..errors import InvalidInput, ErrorItem, EnvError
from ..ids import sha256_json
from ..normalize.fact import Fact
from ..normalize.strategy_plan import expand_plan
from ..rules import ENGINE_VERSION, limits
from ..rules.eval import compile_scoring
from ..rules.runner import evaluate_batch, EvalTimeout, EvalWorkerError
from ..rules.campus import derive, exclude_exps_from_scoring
from ..store import db, matches, runs
from .bootstrap import with_context
from .context import Context
from .staleness import FROZEN_NOTICE, add_warning

def run(ctx: Context, scoring_path: str | None, as_of: str | None, strategy_path: str | None) -> tuple[dict, str]:
    path = (Path(scoring_path).expanduser() if scoring_path else ctx.home.config("scoring.json")).resolve()
    cfg = load_json_file(path, "scoring")
    sc = compile_scoring(cfg)
    scoring_hash = sha256_json(cfg)
    strategy_codes: list[str] = []
    if strategy_path:
        st = load_json_file(Path(strategy_path).expanduser().resolve(), "strategy")
        strategy_codes = list(dict.fromkeys(
            task.filters["experience"]
            for task in expand_plan(st).tasks
            if "experience" in task.filters
        ))
    campus = derive(sc.campus_policy, strategy_codes=strategy_codes,
                    scoring_allowlist=list(sc.experience_allowlist) if sc.experience_allowlist else None,
                    scoring_exclude_exps=exclude_exps_from_scoring(cfg))
    if as_of:
        try:
            as_of_utc = iso_utc(parse_iso(as_of))
        except ValueError as e:
            raise InvalidInput([ErrorItem("SCHEMA_INVALID", f"--as-of 无法解析: {e}", "$.as_of")])
    else:
        as_of_utc = iso_utc(ctx.clock.now())
    bound_profile = ctx.conn.execute("select wmj_profile_revision()").fetchone()[0]
    if bound_profile is None:
        add_warning(ctx, "未找到有效画像版本：本次匹配结果将显示为过期")
    elif bound_profile != sc.profile_revision:
        add_warning(ctx, f"scoring.profile_revision（{sc.profile_revision}）与当前画像版本（{bound_profile}）不一致：结果将显示为过期")

    selection = cfg.get("input_selection", "latest")
    pinned_files = []
    selected = []
    with db.read_tx(ctx.conn):
        if selection == "latest":
            snap = matches.snapshot(ctx.conn)
            selected = [{"job_id": jid, "fact_revision": rev} for jid, rev, _ in snap]
        elif selection == "legacy-20260914":
            pinned_files = cfg["legacy_input"]["files"]
            snap, selected = matches.snapshot_legacy(ctx.conn, pinned_files)
        else:
            raise InvalidInput([ErrorItem("SEMANTIC_INVALID", "未知 input_selection", "$.input_selection")])
    if selection == "legacy-20260914":
        add_warning(ctx, FROZEN_NOTICE)

    facts = [Fact.from_json(json.loads(fj)) for _, _, fj in snap]
    try:
        results = evaluate_batch(sc, facts, campus_exclude=(campus.value == "exclude"),
                                 timeout_sec=limits.EVAL_TIMEOUT_SEC)
    except EvalTimeout as e:
        raise InvalidInput([ErrorItem("SEMANTIC_INVALID", f"{e}；请缩小正则或输入范围", "$")])
    except EvalWorkerError as e:
        raise EnvError("INTERNAL", f"规则求值进程失败：{e}")
    rows = [dict(job_id=jid, fact_revision=rev, dir=r.dir, excluded=r.excluded, rule_score=r.rule_score, tier=r.tier,
                 reasons=r.reasons, exclusion_reasons=r.exclusion_reasons, unknowns=r.unknowns)
            for (jid, rev, _), r in zip(snap, results)]
    by_dir = Counter(r["dir"] for r in rows if r["dir"] and not r["excluded"])
    by_tier = Counter(r["tier"] for r in rows if r["tier"] and not r["excluded"])
    summary = {"jobs_evaluated": len(rows), "classified": sum(1 for r in rows if r["dir"]),
               "excluded": sum(1 for r in rows if r["excluded"]), "by_dir": dict(by_dir), "by_tier": dict(by_tier),
               "campus": {"value": campus.value, "basis": campus.basis, "inputs": campus.inputs},
               "scoring_hash": scoring_hash, "profile_revision": sc.profile_revision, "engine_version": ENGINE_VERSION,
               "as_of": as_of_utc}
    summary["input_selection"] = selection
    input_snapshot = {"selection": selection,
        "files": sorted(pinned_files, key=lambda item: item["name"]), "selected": selected}
    summary["input_snapshot_hash"] = sha256_json(input_snapshot)
    run_config = {"scoring_hash": scoring_hash, "profile_revision": sc.profile_revision,
        "tiers": dict(sc.tiers), "fallback_tier": sc.fallback_tier, "as_of": as_of_utc,
        "campus": {"value": campus.value, "basis": campus.basis}, "scoring_path": str(path),
        "input_selection": selection, "input_snapshot": input_snapshot,
        "input_snapshot_hash": summary["input_snapshot_hash"]}
    with db.write_tx(ctx.conn):
        run_id = runs.create_owned(ctx, kind="match", config=run_config, planned=len(rows))
        matches.insert_results(ctx.conn, run_id, rows, scoring_hash=scoring_hash, profile_revision=sc.profile_revision,
                               engine_version=ENGINE_VERSION, as_of=as_of_utc)
        matches.commit_run(ctx.conn, ctx.clock, run_id, completed=len(rows), summary=summary)
    data = {k: v for k, v in summary.items() if k != "campus"}
    data["campus"] = {"value": campus.value, "basis": campus.basis}
    return data, run_id

def register(sub, set_handler):
    p = sub.add_parser("match", help="以固定快照计算并事务提交一次 match_run")
    p.add_argument("--scoring"); p.add_argument("--as-of"); p.add_argument("--strategy")
    set_handler(p, "match", lambda ns, w: with_context(ns, w, lambda ctx: run(ctx, ns.scoring, ns.as_of, ns.strategy), write=True))
