from __future__ import annotations
import hashlib, json, os, tempfile
from dataclasses import dataclass
from pathlib import Path
from .errors import EnvError, InvalidInput, ErrorItem

DEFAULT_HOME = "~/.where-my-job"
CONFIG_FILES = ("profile.json", "scoring.json", "panel.json", "settings.json")

@dataclass(frozen=True)
class Layout:
    root: Path

    @property
    def state(self) -> Path: return self.root / "state"
    @property
    def db_path(self) -> Path: return self.state / "where-my-job.sqlite3"
    @property
    def lock_path(self) -> Path: return self.state / "browser.lock"
    @property
    def migrations_lock(self) -> Path: return self.state / "migrations.lock"
    @property
    def runs_dir(self) -> Path: return self.state / "runs"
    @property
    def backups(self) -> Path: return self.state / "backups"
    @property
    def managed_outputs_path(self) -> Path: return self.state / "managed_outputs.json"
    @property
    def panel_dir(self) -> Path: return self.root / "panel"
    @property
    def panel_latest(self) -> Path: return self.panel_dir / "latest.html"
    @property
    def browser_profile(self) -> Path: return self.root / "browser-profile"
    @property
    def strategies(self) -> Path: return self.root / "strategies"
    @property
    def streams(self) -> Path: return self.root / "streams"
    @property
    def resume(self) -> Path: return self.root / "resume"

    def config(self, name: str) -> Path:
        return self.root / name

def home() -> Path:
    return Path(os.environ.get("WMJ_HOME") or DEFAULT_HOME).expanduser().resolve()

def _package_root() -> Path:
    return Path(__file__).resolve().parent

def install_root() -> Path:
    """源码开发时为仓库根（含 pyproject.toml），安装后为包目录本身。"""
    pkg = _package_root()
    if pkg.parent.name == "src" and (pkg.parent.parent / "pyproject.toml").exists():
        return pkg.parent.parent
    return pkg

def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents

def _credential_roots() -> list[Path]:
    h = Path.home()
    return [(h / p).resolve() for p in (".ssh", ".aws", ".gnupg", ".config/gcloud", "Library/Keychains",
                                        "Library/Application Support/Google/Chrome")]

def forbidden_roots(lay: Layout) -> list[Path]:
    """内部与导出写入都不允许落入的位置。"""
    return [install_root(), *_credential_roots(), lay.browser_profile.resolve()]

def _layout_dirs(lay: Layout) -> list[Path]:
    return [lay.root, lay.state, lay.runs_dir, lay.backups, lay.panel_dir, lay.strategies, lay.streams, lay.resume]

def ensure_layout() -> Layout:
    root = home()
    inst = install_root()
    if _within(root, inst) or _within(inst, root):
        raise EnvError("PERMISSION_DENIED", f"WMJ_HOME 不能与程序安装目录重叠: {root}")
    for cred in _credential_roots():
        if _within(root, cred):
            raise EnvError("PERMISSION_DENIED", f"WMJ_HOME 不能位于凭证目录内: {root}")
    lay = Layout(root)
    for d in _layout_dirs(lay):                    # 先查全部，再创建
        if d.is_symlink():
            raise EnvError("PERMISSION_DENIED", f"数据目录不能是符号链接: {d}")
        if d.exists() and (not d.is_dir() or d.resolve() != d):
            raise EnvError("PERMISSION_DENIED", f"数据目录必须是位于数据根内的真实目录: {d}")
    for d in _layout_dirs(lay):
        try:
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d, 0o700)
        except PermissionError as e:
            raise EnvError("PERMISSION_DENIED", f"无法创建或设置目录权限 {d}: {e.strerror}") from e
        except OSError as e:
            raise EnvError("DISK_ERROR", f"无法创建目录 {d}: {e.strerror}") from e
    if not os.access(lay.state, os.W_OK):
        raise EnvError("PERMISSION_DENIED", f"数据目录不可写: {lay.state}")
    return lay

def _absolute(target: Path | str) -> Path:
    t = Path(target).expanduser()
    return t if t.is_absolute() else Path.cwd() / t

def _deny(message: str) -> InvalidInput:
    return InvalidInput([ErrorItem("SEMANTIC_INVALID", message, "$.path")])

def _check_target(target: Path | str, lay: Layout | None) -> Path:
    lay = lay or Layout(home())
    t = _absolute(target)
    if t.is_symlink():
        real = Path(os.path.realpath(t))
        if not _within(real, lay.root):
            raise _deny(f"目标是指向数据目录外的符号链接: {t}")
    else:
        real = t.parent.resolve() / t.name
    for bad in forbidden_roots(lay):
        if _within(real, bad):
            raise _deny(f"禁止写入受保护位置: {t}")
    return real

def check_export_target(target: Path | str, lay: Layout) -> Path:
    t = _absolute(target)
    if t.is_symlink():
        raise _deny(f"导出目标不能是符号链接: {t}")
    if not t.parent.is_dir():
        raise _deny(f"导出目录不存在: {t.parent}")
    real = t.parent.resolve() / t.name
    if real.exists() and not real.is_file():
        raise _deny(f"导出目标必须是普通文件: {t}")
    guarded = forbidden_roots(lay) + [lay.state.resolve(), lay.strategies.resolve(), lay.streams.resolve()]
    guarded += [lay.config(n).resolve() for n in CONFIG_FILES]
    for bad in guarded:
        if _within(real, bad):
            raise _deny(f"导出目标位于受保护位置: {t}")
    return real

def _atomic_write(real: Path, data: bytes, mode: int) -> None:
    try:
        real.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=f".{real.name}.", suffix=".tmp", dir=real.parent)
    except PermissionError as e:
        raise EnvError("PERMISSION_DENIED", f"无权写入 {real.parent}: {e.strerror}") from e
    except OSError as e:
        raise EnvError("DISK_ERROR", f"无法写入 {real.parent}: {e.strerror}") from e
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        if isinstance(e, PermissionError):
            raise EnvError("PERMISSION_DENIED", f"无权写入 {real}: {e.strerror}") from e
        if isinstance(e, OSError):
            raise EnvError("DISK_ERROR", f"写入失败 {real}: {e.strerror}") from e
        raise

def atomic_write_text(target: Path | str, text: str, mode: int = 0o600, lay: Layout | None = None) -> None:
    _atomic_write(_check_target(target, lay), text.encode("utf-8"), mode)

def atomic_write_bytes(target: Path | str, data: bytes, mode: int = 0o600, lay: Layout | None = None) -> None:
    _atomic_write(_check_target(target, lay), data, mode)

def export_write_text(target: Path | str, text: str, lay: Layout, mode: int = 0o600) -> Path:
    real = check_export_target(target, lay)
    _atomic_write(real, text.encode("utf-8"), mode)
    return real

# ---- 受管输出清单 ----

def managed_outputs(lay: Layout) -> list[dict]:
    p = lay.managed_outputs_path
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise EnvError("DISK_ERROR", f"受管输出清单无法读取: {e}") from e
    if not isinstance(data, list):
        raise EnvError("DISK_ERROR", "受管输出清单格式错误")
    return [e for e in data if isinstance(e, dict) and isinstance(e.get("path"), str)
            and isinstance(e.get("sha256"), str)]

def _write_manifest(lay: Layout, entries: list[dict]) -> None:
    atomic_write_text(lay.managed_outputs_path, json.dumps(entries, ensure_ascii=False, indent=1), lay=lay)

def register_managed_output(lay: Layout, path: Path | str, sha256: str) -> None:
    real = str(_absolute(path).resolve())
    entries = [e for e in managed_outputs(lay) if e["path"] != real]
    entries.append({"path": real, "sha256": sha256})
    _write_manifest(lay, entries)

def _sha256_of(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def invalidate_managed_outputs(lay: Layout, *, dry_run: bool) -> dict:
    """删除 sha256 仍匹配的受管文件；被改写、符号链接、受保护位置的文件保留并报告。"""
    removed_key = "would_remove" if dry_run else "removed"
    result = {removed_key: [], "missing": [], "kept_modified": [], "failed": []}
    remaining: list[dict] = []
    guarded = forbidden_roots(lay)
    for e in managed_outputs(lay):
        p = Path(e["path"])
        if p.is_symlink() or (p.exists() and not p.is_file()) or any(_within(p.resolve(), b) for b in guarded):
            result["kept_modified"].append(e["path"])
            continue
        if not p.exists():
            result["missing"].append(e["path"])
            continue
        try:
            digest = _sha256_of(p)
        except OSError:
            result["failed"].append(e["path"]); remaining.append(e)
            continue
        if digest != e["sha256"]:
            result["kept_modified"].append(e["path"])
            continue
        if dry_run:
            result[removed_key].append(e["path"]); remaining.append(e)
            continue
        try:
            p.unlink()
            result[removed_key].append(e["path"])
        except OSError:
            result["failed"].append(e["path"]); remaining.append(e)
    if not dry_run:
        _write_manifest(lay, remaining)
    return result

def clear_migration_backups(lay: Layout, *, dry_run: bool) -> dict:
    """迁移备份含完整业务库；清理数据时保守全部清除。"""
    removed_key = "would_remove" if dry_run else "removed"
    result = {removed_key: [], "failed": []}
    for f in sorted(lay.backups.glob("*.sqlite3")):
        if dry_run:
            result[removed_key].append(str(f)); continue
        try:
            f.unlink(); result[removed_key].append(str(f))
        except OSError:
            result["failed"].append(str(f))
    return result
