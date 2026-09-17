from __future__ import annotations
import fcntl, hashlib, os, sqlite3, uuid
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
from ..clock import Clock, SystemClock, iso_utc
from ..errors import EnvError, WmjError

Connection = sqlite3.Connection        # 纯类型别名；store 之外的模块从这里导入，不直接 import sqlite3
BUSY_TIMEOUT_MS = 5000
MIN_SQLITE = (3, 38, 0)

def capabilities() -> dict:
    version = tuple(int(x) for x in sqlite3.sqlite_version.split("."))
    mem = sqlite3.connect(":memory:")
    try:
        mem.execute("create table t(x)")
        def ok(sql: str) -> bool:
            try:
                mem.execute(sql).fetchall()
                return True
            except sqlite3.Error:
                return False
        return {
            "sqlite_version": sqlite3.sqlite_version,
            "version_ok": version >= MIN_SQLITE,
            "json1": ok("select json_extract('{\"a\":1}','$.a')"),
            "window_functions": ok("select row_number() over (order by 1)"),
            "returning": ok("insert into t values(1) returning x"),
        }
    finally:
        mem.close()

def require_capabilities() -> None:
    caps = capabilities()
    missing = [k for k in ("version_ok", "json1", "window_functions", "returning") if not caps[k]]
    if missing:
        raise EnvError("MISSING_DEPENDENCY", f"SQLite {caps['sqlite_version']} 缺少能力: {', '.join(missing)}")

def map_sqlite_error(exc: BaseException) -> WmjError | None:
    """把资源类 SQLite 错误映射为固定错误码；约束错误与未知错误返回 None。"""
    if not isinstance(exc, sqlite3.Error) or isinstance(exc, sqlite3.IntegrityError):
        return None
    name = getattr(exc, "sqlite_errorname", "") or ""
    msg = str(exc).lower()
    if name.startswith(("SQLITE_BUSY", "SQLITE_LOCKED")) or "locked" in msg or "busy" in msg:
        return EnvError("DB_BUSY", "数据库正被其他进程占用，稍后重试")
    if (name.startswith(("SQLITE_READONLY", "SQLITE_PERM", "SQLITE_CANTOPEN", "SQLITE_AUTH"))
            or "readonly" in msg or "permission" in msg or "unable to open" in msg):
        return EnvError("PERMISSION_DENIED", "数据库文件不可读写")
    if name.startswith(("SQLITE_FULL", "SQLITE_IOERR")) or "disk" in msg or "full" in msg or "i/o" in msg:
        return EnvError("DISK_ERROR", "数据库磁盘读写失败")
    return None

def bind_profile_revision(conn: Connection, revision: str | None) -> None:
    conn.create_function("wmj_profile_revision", 0, lambda: revision)

def open_db(path: Path, clock: Clock | None = None) -> Connection:
    require_capabilities()
    clock = clock or SystemClock()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
    except PermissionError as e:
        raise EnvError("PERMISSION_DENIED", f"数据库文件权限错误 {path}: {e.strerror}") from e
    except OSError as e:
        raise EnvError("DISK_ERROR", f"无法创建数据库文件 {path}: {e.strerror}") from e
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=BUSY_TIMEOUT_MS / 1000)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"pragma busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("pragma foreign_keys = on")
        # 切换 WAL 需要短暂的独占访问。并发首次启动时，若不串行，busy_timeout 对该 pragma 不生效，
        # 会直接报 database is locked。与迁移共用 state/migrations.lock（数据库与锁同在 state/）。
        wal_lock = _flock_path(path.parent / "migrations.lock")
        try:
            conn.execute("pragma journal_mode = wal")
        finally:
            _release_lock(wal_lock)
    except sqlite3.Error as e:
        conn.close()
        raise (map_sqlite_error(e) or EnvError("DISK_ERROR", f"无法打开数据库: {e}")) from e
    as_of = iso_utc(clock.now())
    conn.create_function("wmj_as_of", 0, lambda: as_of, deterministic=True)
    bind_profile_revision(conn, None)
    return conn

def _migration_files() -> list[tuple[int, str, str]]:
    root = resources.files("where_my_job.store.migrations")
    out = []
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".sql"):
            out.append((int(entry.name.split("_", 1)[0]), entry.name, entry.read_text(encoding="utf-8")))
    return out

def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()

def _split_statements(sql: str) -> list[str]:
    """去掉整行注释后按分号切分；迁移文件的行尾注释不含半角分号。"""
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]

def _flock_path(lock_path: Path) -> int:
    """以 0600 打开（必要时创建）锁文件并阻塞取得独占 flock，返回文件描述符。"""
    try:
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    except PermissionError as e:
        raise EnvError("PERMISSION_DENIED", f"无法创建迁移锁: {e.strerror}") from e
    except OSError as e:
        raise EnvError("DISK_ERROR", f"无法创建迁移锁: {e.strerror}") from e
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
    except OSError as e:
        os.close(fd)
        raise EnvError("DISK_ERROR", f"无法获取迁移锁: {e.strerror}") from e
    return fd

def _acquire_migration_lock(lay) -> int:
    return _flock_path(lay.migrations_lock)

def _release_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)

def _backup_before_migrate(conn: Connection, lay, clock: Clock, target_version: int) -> None:
    stamp = iso_utc(clock.now())[:19].replace(":", "").replace("-", "")
    dest = lay.backups / f"pre-migrate-{target_version:04d}-{stamp}-{uuid.uuid4().hex[:12]}.sqlite3"
    created = False
    try:
        lay.backups.mkdir(parents=True, exist_ok=True)
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        os.close(fd)
        target = sqlite3.connect(str(dest))
        try:
            conn.backup(target)
        finally:
            target.close()
        os.chmod(dest, 0o600)
    except BaseException as e:
        if created:
            try:
                dest.unlink()
            except OSError:
                pass
        if isinstance(e, PermissionError):
            raise EnvError("PERMISSION_DENIED", f"迁移前备份失败，未执行迁移: {e.strerror}") from e
        if isinstance(e, (OSError, sqlite3.Error)):
            raise EnvError("DISK_ERROR", f"迁移前备份失败，未执行迁移: {e}") from e
        raise

def migrate(conn: Connection, lay, clock: Clock | None = None) -> list[int]:
    """持迁移锁应用未应用的迁移；已有迁移的库先备份。返回本次应用的版本列表。"""
    clock = clock or SystemClock()
    files = _migration_files()
    lock_fd = _acquire_migration_lock(lay)
    try:
        conn.execute("""create table if not exists schema_migrations(
            version integer primary key, checksum text not null, applied_at text not null)""")
        applied = {r[0]: r[1] for r in conn.execute("select version, checksum from schema_migrations")}
        for v, name, sql in files:
            if v in applied and applied[v] != _checksum(sql):
                raise EnvError("MISSING_DEPENDENCY", f"迁移 {name} 内容与已应用版本不一致，拒绝启动")
        pending = [(v, name, sql) for v, name, sql in files if v not in applied]
        if not pending:
            return []
        if applied:
            _backup_before_migrate(conn, lay, clock, max(v for v, _, _ in pending))
        done: list[int] = []
        conn.execute("begin immediate")
        try:
            applied_now = {r[0] for r in conn.execute("select version from schema_migrations")}
            for v, name, sql in pending:
                if v in applied_now:
                    continue
                for stmt in _split_statements(sql):
                    conn.execute(stmt)
                conn.execute("insert into schema_migrations(version, checksum, applied_at) values (?,?,?)",
                             (v, _checksum(sql), iso_utc(clock.now())))
                done.append(v)
            conn.execute("commit")
        except BaseException:
            try:
                conn.execute("rollback")
            except sqlite3.Error:
                pass
            raise
        return done
    except sqlite3.Error as e:
        mapped = map_sqlite_error(e)
        if mapped is not None:
            raise mapped from e
        raise
    finally:
        _release_lock(lock_fd)

@contextmanager
def write_tx(conn: Connection):
    try:
        conn.execute("begin immediate")
    except sqlite3.Error as e:
        mapped = map_sqlite_error(e)
        if mapped is not None:
            raise mapped from e
        raise
    try:
        yield conn
        conn.execute("commit")
    except BaseException as e:
        try:
            conn.execute("rollback")
        except sqlite3.Error:
            pass
        mapped = map_sqlite_error(e)
        if mapped is not None:
            raise mapped from e
        raise

@contextmanager
def read_tx(conn: Connection):
    conn.execute("begin")
    try:
        yield conn
    finally:
        try:
            conn.execute("commit")
        except sqlite3.Error:
            pass
