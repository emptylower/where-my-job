"""network_policy_state 的唯一读写入口。读不建行；写用 upsert。"""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from urllib.parse import quote

def _row_to_state(row) -> dict | None:
    if row is None:
        return None
    return {"ledger": json.loads(row["ledger_json"] or "[]"), "cooldown_until": row["cooldown_until"],
            "cooldown_reason": row["cooldown_reason"], "last_action_at": row["last_action_at"],
            "updated_at": row["updated_at"]}

def read_state(conn: sqlite3.Connection, profile_id: str) -> dict | None:
    conn.row_factory = sqlite3.Row
    row = conn.execute("""select ledger_json, cooldown_until, cooldown_reason, last_action_at, updated_at
                          from network_policy_state where browser_profile_id=?""", (profile_id,)).fetchone()
    return _row_to_state(row)

def read_state_readonly(db_path: Path, profile_id: str) -> dict | None:
    """dry-run 专用：只读打开且不创建任何文件；数据库或表不存在返回 None。

    打开方式按 WAL 附属文件的现状选择：
    - 没有 `-wal`：没有活动写者，上次连接已检查点并删除附属文件。用 `mode=ro&immutable=1`，
      SQLite 不创建 `-shm`/`-wal`，也不加文件锁。
    - `-wal` 与 `-shm` 并存：另有连接正在使用 WAL，`-shm` 必然已与 `-wal` 同时存在。用 `mode=ro`
      只读取这两个既有文件，不会生成新文件；此时不能用 immutable，否则会忽略 `-wal` 中尚未检查点的冷却写入。
    - 只有 `-wal` 没有 `-shm`：异常退出留下的日志。只读打开会新建 `-shm`，因此拒绝（`DB_BUSY`），
      提示先运行一次普通命令完成恢复，不假装没有冷却。
    """
    from ..errors import EnvError
    p = Path(db_path)
    if not p.exists():
        return None
    wal, shm = p.with_name(p.name + "-wal"), p.with_name(p.name + "-shm")
    if not wal.exists():
        uri = f"file:{quote(str(p))}?mode=ro&immutable=1"
    elif shm.exists():
        uri = f"file:{quote(str(p))}?mode=ro"
    else:
        raise EnvError("DB_BUSY", "数据库留有未恢复的写入日志；先运行 where-my-job status 完成恢复，再做 dry-run")
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.OperationalError:
        return None
    try:
        conn.row_factory = sqlite3.Row
        try:
            return read_state(conn, profile_id)
        except sqlite3.OperationalError:
            return None
    finally:
        conn.close()

def upsert_ledger(conn, profile_id: str, entries: list[dict], last_action_at: str, updated_at: str) -> None:
    conn.execute("""insert into network_policy_state(browser_profile_id, ledger_json, last_action_at, updated_at)
                    values (?,?,?,?)
                    on conflict(browser_profile_id) do update set
                      ledger_json=excluded.ledger_json, last_action_at=excluded.last_action_at,
                      updated_at=excluded.updated_at""",
                 (profile_id, json.dumps(entries, ensure_ascii=False, separators=(",", ":")), last_action_at, updated_at))

def upsert_cooldown(conn, profile_id: str, until: str, reason: str, updated_at: str) -> None:
    conn.execute("""insert into network_policy_state(browser_profile_id, ledger_json, cooldown_until, cooldown_reason, updated_at)
                    values (?, '[]', ?, ?, ?)
                    on conflict(browser_profile_id) do update set
                      cooldown_until=excluded.cooldown_until, cooldown_reason=excluded.cooldown_reason,
                      updated_at=excluded.updated_at""",
                 (profile_id, until, reason, updated_at))
