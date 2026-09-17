# src/where_my_job/store/matches.py
from __future__ import annotations
import json
import re
from typing import NoReturn
from ..clock import Clock
from ..errors import ErrorItem, InvalidInput
from ..ids import canonical_json, sha256_json
from ..normalize.fact import fact_hash
from ..normalize.legacy import LegacyRecordError
from ..normalize.legacy_20260914 import fact_for_replay
from .db import Connection
from . import runs

def begin_run(conn: Connection, clock: Clock, *, scoring_hash: str, profile_revision: str, tiers: dict,
              fallback_tier: str, as_of: str, campus: dict, planned: int, scoring_path: str | None = None) -> str:
    """仓储单测用；生产路径由 service.match 通过 runs.create_owned 创建批次。"""
    config = {"scoring_hash": scoring_hash, "profile_revision": profile_revision, "tiers": tiers,
              "fallback_tier": fallback_tier, "as_of": as_of, "campus": campus, "scoring_path": scoring_path,
              "input_selection": "latest"}
    return runs.create(conn, clock, kind="match", config=config, planned=planned)

def insert_results(conn, match_run_id: str, rows: list[dict], *, scoring_hash: str, profile_revision: str,
                   engine_version: str, as_of: str) -> None:
    conn.executemany("""insert into match_results(match_run_id, job_id, fact_revision, scoring_hash, profile_revision,
                        engine_version, as_of, dir, excluded, rule_score, tier, reasons_json, exclusion_reasons_json, unknowns_json)
                        values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     [(match_run_id, r["job_id"], r["fact_revision"], scoring_hash, profile_revision, engine_version, as_of,
                       r["dir"], int(r["excluded"]), r["rule_score"], r["tier"], canonical_json(r["reasons"]),
                       canonical_json(r["exclusion_reasons"]), canonical_json(r["unknowns"])) for r in rows])

def commit_run(conn, clock: Clock, match_run_id: str, *, completed: int, summary: dict) -> None:
    runs.finish(conn, clock, match_run_id, status="ok", completed=completed, summary=summary)

def current_run(conn):
    return conn.execute("""select run_id, config_json, started_at, summary_json from runs
                           where kind='match' and status='ok' order by started_at desc, rowid desc limit 1""").fetchone()

def snapshot(conn) -> list[tuple[str, str, str]]:
    """(job_id, fact_revision, fact_json) 当前有效事实；没有观察的岗位不参与。"""
    return [(r[0], r[1], r[2]) for r in conn.execute(
        """select j.job_id, s.content_hash, s.fact_json from jobs j join sightings s on s.observation_id = j.current_sighting_id
           order by j.job_id""")]

def snapshot_legacy(conn, pinned_files: list[dict]) -> tuple[list[tuple[str, str, str]], list[dict]]:
    """调用方持有 read_tx；返回评分输入和逐岗选择依据。"""
    def fail(message: str, code: str = "SEMANTIC_INVALID") -> NoReturn:
        raise InvalidInput([ErrorItem(code, message, "$.legacy_input.files")])
    if not isinstance(pinned_files, list) or not pinned_files:
        fail("冻结输入必须给出非空文件清单")
    names, hashes = set(), set()
    for source in pinned_files:
        if not isinstance(source, dict) or set(source) != {"name", "sha256"}:
            fail("冻结文件项只能包含 name 与 sha256")
        name, digest = source["name"], source["sha256"]
        if not isinstance(name, str) or not re.fullmatch(r"[^_/\\]+_[^/\\]+\.json", name):
            fail("冻结来源名必须为城市_关键词.json，不得含目录")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            fail("冻结文件 sha256 必须为64位小写十六进制")
        if name in names or digest in hashes:
            fail("冻结文件名和内容 hash 必须各自唯一")
        names.add(name)
        hashes.add(digest)
    snapshot, selected = [], []
    seen_legacy_ids, seen_job_ids = set(), set()
    for source in sorted(pinned_files, key=lambda item: item["name"]):
        name, digest = source["name"], source["sha256"]
        rows = conn.execute("""SELECT s.observation_id, s.job_id, s.item_index,
                  s.raw_json, s.raw_hash, t.query_json, t.status
            FROM sightings s
            JOIN run_tasks t ON t.task_id=s.task_id AND t.run_id=s.run_id
            JOIN runs r ON r.run_id=s.run_id
            WHERE s.file_sha256=? AND s.raw_kind='legacy_mapped' AND r.kind='import'
            ORDER BY s.item_index""", (digest,)).fetchall()
        if not rows:
            fail(f"{name}: 冻结文件尚未完整导入或已删除", "NOT_FOUND")
        expected_count = None
        for row in rows:
            metadata = json.loads(row["query_json"])
            if (not isinstance(metadata, dict) or metadata.get("source_name") != name
                    or metadata.get("sha256") != digest or metadata.get("record_errors") != []
                    or row["status"] != "ok"):
                fail(f"{name}: 来源元数据或文件提交状态不符合冻结输入")
            count = metadata.get("source_item_count")
            if type(count) is not int or count < 1:
                fail(f"{name}: 缺少有效 source_item_count，不能认证完整冻结输入")
            if expected_count is None:
                expected_count = count
            elif count != expected_count:
                fail(f"{name}: 同一文件记录总数元数据不一致")
        if len(rows) != expected_count or any(row["item_index"] != index for index, row in enumerate(rows)):
            fail(f"{name}: 观察记录不完整，不能降级为剩余记录", "NOT_FOUND")
        for row in rows:
            if row["raw_json"] is None:
                fail(f"{name}: 冻结原记录已被裁剪，不能以当前事实替代", "NOT_FOUND")
            record = json.loads(row["raw_json"])
            if not isinstance(record, dict) or sha256_json(record) != row["raw_hash"]:
                fail(f"{name}: 冻结原记录校验失败")
            legacy_id = record.get("job_id")
            if legacy_id is None or legacy_id == "":
                continue
            if not isinstance(legacy_id, str):
                fail(f"{name}: 旧 job_id 必须为文本")
            if legacy_id in seen_legacy_ids:
                continue
            seen_legacy_ids.add(legacy_id)
            if row["job_id"] in seen_job_ids:
                fail(f"{name}: 两个旧 job_id 映射同一标准岗位，无法无损冻结")
            if row["job_id"] != "boss:" + str(record.get("encrypt_job_id") or "").strip():
                fail(f"{name}: 原记录与标准岗位身份不一致")
            try:
                fact = fact_for_replay(record, name)
            except LegacyRecordError as exc:
                fail(f"{name}: 冻结原记录无法映射：{exc}")
            revision = fact_hash(fact)
            seen_job_ids.add(row["job_id"])
            snapshot.append((row["job_id"], revision, canonical_json(fact.to_json())))
            selected.append({"job_id": row["job_id"], "observation_id": row["observation_id"],
                "source_name": name, "file_sha256": digest, "item_index": row["item_index"],
                "fact_revision": revision})
    return snapshot, selected
