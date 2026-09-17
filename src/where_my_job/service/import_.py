from __future__ import annotations
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from ..clock import parse_iso
from ..config.loader import load_json_file
from ..errors import InvalidInput, EnvError, Partial, ErrorItem
from ..importer.legacy import read_legacy_file, LegacyFileError, LegacyFile
from ..store import db, runs, companies, jobs, sightings
from .bootstrap import with_context
from .context import Context

DEFAULT_TZ_ASSUMPTION = "Asia/Shanghai"

def _absolute(p: str | Path, base: Path) -> Path:
    q = Path(p).expanduser()
    return (q if q.is_absolute() else base / q).resolve()

def _entries(files: list[str], manifest: str | None) -> tuple[str, list[dict]]:
    tz = DEFAULT_TZ_ASSUMPTION
    raw: list[tuple[Path, str | None]] = []
    if manifest:
        mpath = _absolute(manifest, Path.cwd())
        m = load_json_file(mpath, "import_manifest")
        tz = m.get("timezone_assumption", tz)
        raw += [(_absolute(f["path"], mpath.parent), f.get("sha256")) for f in m["files"]]
    raw += [(_absolute(f, Path.cwd()), None) for f in files]
    if not raw:
        raise InvalidInput([ErrorItem("SCHEMA_INVALID", "至少给一个文件或 --manifest", "$.files")])
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise InvalidInput([ErrorItem("SEMANTIC_INVALID", f"未知时区 {tz}", "$.timezone_assumption")])
    by_path: dict[Path, dict] = {}
    entries: list[dict] = []
    for index, (path, sha) in enumerate(raw):
        if path in by_path:
            known = by_path[path]
            if sha and known["sha256"] and sha != known["sha256"]:
                raise InvalidInput([ErrorItem("SEMANTIC_INVALID", f"同一文件给出了不同的 sha256: {path.name}",
                                              f"$.files[{index}]")])
            known["sha256"] = known["sha256"] or sha
            continue
        entry = {"source_index": index, "path": path, "sha256": sha}
        by_path[path] = entry
        entries.append(entry)
    return tz, entries

def _source_meta(index: int, lf: LegacyFile) -> dict:
    return {"keyword": lf.keyword, "city": lf.city, "filters": lf.filters,
            "source_name": lf.name, "source_index": index, "sha256": lf.sha256,
            "source_item_count": lf.source_item_count, "record_errors": lf.errors}

def _import_one(ctx: Context, run_id: str, index: int, lf: LegacyFile, *, committed_files: int, totals: dict) -> dict:
    stats = {"inserted": 0, "skipped": 0, "record_errors": len(lf.errors)}
    with db.write_tx(ctx.conn):
        task_id = runs.add_task(ctx.conn, ctx.clock, run_id, task_key=f"{index:06d}:{lf.name}",
                                query=_source_meta(index, lf))
        observed = parse_iso(lf.observed_at_utc) if lf.observed_at_utc else None
        touched: set[str] = set()
        for item_index, m in lf.records:
            if sightings.exists_file_key(ctx.conn, lf.sha256, item_index):
                stats["skipped"] += 1
                continue
            if m.company_id:
                companies.ensure(ctx.conn, ctx.clock, m.company_id, "boss", m.company_id.split(":", 1)[1], m.company_name)
            jobs.ensure(ctx.conn, ctx.clock, m.job_id, "boss", m.source_job_id, m.legacy_job_id, m.company_id)
            sightings.insert(ctx.conn, ctx.clock, job_id=m.job_id, run_id=run_id, task_id=task_id,
                             file_sha256=lf.sha256, item_index=item_index, page=None,
                             observed_at=observed, observed_at_raw=lf.observed_at_raw,
                             time_precision="file_snapshot", tz_assumption=lf.tz_assumption,
                             raw_kind="legacy_mapped", raw=m.raw_private, fact=m.fact)
            touched.add(m.job_id)
            stats["inserted"] += 1
        for job_id in sorted(touched):
            jobs.refresh_current(ctx.conn, ctx.clock, job_id)
        if lf.records and lf.errors:
            status, code, msg = "ok", "SOME_FILES_INVALID", f"{len(lf.errors)} 条记录无效"
        elif lf.errors:
            status, code, msg = "failed", "ALL_FILES_INVALID", f"{len(lf.errors)} 条记录全部无效"
        elif not lf.records:
            status, code, msg = "empty", None, None
        else:
            status, code, msg = "ok", None, None
        runs.finish_task(ctx.conn, ctx.clock, task_id, status=status, failure_code=code, failure_message=msg)
        runs.update_progress(ctx.conn, run_id, completed=committed_files + 1,
                             summary=_summary({k: totals[k] + stats[k] for k in totals}, []))
    return stats

def _summary(totals: dict, failed: list[dict]) -> dict:
    return {"observations_inserted": totals["inserted"], "observations_skipped": totals["skipped"],
            "record_errors": totals["record_errors"], "files_failed": [f["source_name"] for f in failed]}

def _data(ctx: Context, totals: dict, committed: list[str], failed: list[dict], tz: str, unfinished: list[str]) -> dict:
    try:
        jobs_total = ctx.conn.execute("select count(*) from jobs").fetchone()[0]
    except Exception:
        jobs_total = None
    return {"files_ok": len(committed), "files_committed": committed,
            "files_failed": [f["source_name"] for f in failed], "files_unfinished": unfinished,
            "record_errors": totals["record_errors"], "observations_inserted": totals["inserted"],
            "observations_skipped": totals["skipped"], "jobs_total": jobs_total, "tz_assumption": tz}

def _finish_quietly(ctx: Context, run_id: str, status: str, completed: int, totals: dict, failed: list[dict]) -> None:
    try:
        with db.write_tx(ctx.conn):
            runs.finish(ctx.conn, ctx.clock, run_id, status=status, completed=completed, summary=_summary(totals, failed))
    except Exception:
        pass      # 尽力写终态，不覆盖原始错误

def run(ctx: Context, files: list[str], manifest: str | None) -> tuple[dict, str]:
    tz, entries = _entries(files, manifest)
    loaded: list[tuple[int, LegacyFile]] = []
    failed: list[dict] = []
    for e in entries:
        try:
            lf = read_legacy_file(e["path"], tz_assumption=tz)
            if e["sha256"] and lf.sha256 != e["sha256"]:
                raise LegacyFileError(f"{lf.name}: sha256 不匹配（期望 {e['sha256'][:8]}…，实际 {lf.sha256[:8]}…）")
            loaded.append((e["source_index"], lf))
        except LegacyFileError as exc:
            failed.append({"source_index": e["source_index"], "source_name": e["path"].name, "message": str(exc)})
    if sum(len(lf.records) for _, lf in loaded) == 0:
        issues = [ErrorItem("ALL_FILES_INVALID", f["message"], f"$.files[{f['source_index']}]") for f in failed]
        issues += [ErrorItem("ALL_FILES_INVALID", f"{lf.name}: 没有任何有效记录（{len(lf.errors)} 条记录错误）",
                             f"$.files[{i}]") for i, lf in loaded]
        raise InvalidInput(issues or [ErrorItem("ALL_FILES_INVALID", "没有可导入的有效记录", "$.files")])

    config = {"files": [_source_meta(i, lf) for i, lf in loaded], "failed": failed, "tz_assumption": tz}
    run_id = runs.create_owned(ctx, kind="import", config=config, planned=len(entries))
    totals = {"inserted": 0, "skipped": 0, "record_errors": 0}
    committed: list[str] = []
    for pos, (index, lf) in enumerate(loaded):
        try:
            stats = _import_one(ctx, run_id, index, lf, committed_files=len(committed), totals=totals)
        except EnvError as exc:
            unfinished = [other.name for _, other in loaded[pos:]]
            _finish_quietly(ctx, run_id, "partial" if committed else "failed", len(committed), totals, failed)
            if committed:
                raise Partial("PARTIAL_RESULT", f"{exc.message}；已提交 {len(committed)} 个文件，其余未完成",
                              data=_data(ctx, totals, committed, failed, tz, unfinished), run_id=run_id) from exc
            exc.run_id = run_id
            raise
        except Exception:
            _finish_quietly(ctx, run_id, "failed", len(committed), totals, failed)
            raise
        committed.append(lf.name)
        for k in totals:
            totals[k] += stats[k]

    partial = bool(failed) or totals["record_errors"] > 0
    data = _data(ctx, totals, committed, failed, tz, [])
    try:
        with db.write_tx(ctx.conn):
            runs.finish(ctx.conn, ctx.clock, run_id, status="partial" if partial else "ok",
                        completed=len(committed), summary=_summary(totals, failed))
    except EnvError as exc:
        raise Partial("PARTIAL_RESULT", f"数据已提交，但写入运行终态失败：{exc.message}", data=data, run_id=run_id) from exc
    if partial:
        messages = [f["message"] for f in failed]
        if totals["record_errors"]:
            messages.append(f"{totals['record_errors']} 条记录无效，详见 run_tasks.query_json.record_errors")
        raise Partial("SOME_FILES_INVALID", "; ".join(messages), data=data, run_id=run_id)
    return data, run_id

def register(sub, set_handler):
    p = sub.add_parser("import", help="导入旧列表 JSON 文件（显式清单，内容哈希幂等）")
    p.add_argument("files", nargs="*")
    p.add_argument("--manifest", help="import_manifest JSON")
    set_handler(p, "import", lambda ns, warnings: with_context(ns, warnings, lambda ctx: run(ctx, ns.files, ns.manifest),
                                                               write=True))
