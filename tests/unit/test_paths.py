import json, os, stat, pathlib, pytest
from where_my_job import paths
from where_my_job.errors import EnvError, InvalidInput
from where_my_job.ids import sha256_bytes

def _home(tmp_path, monkeypatch, name="h"):
    monkeypatch.setenv("WMJ_HOME", str(tmp_path / name))
    return paths.ensure_layout()

def test_home_from_env_and_layout(tmp_path, monkeypatch):
    lay = _home(tmp_path, monkeypatch)
    assert lay.root == (tmp_path / "h").resolve()
    assert lay.db_path == lay.root / "state" / "where-my-job.sqlite3"
    assert lay.runs_dir == lay.root / "state" / "runs"
    assert lay.managed_outputs_path == lay.root / "state" / "managed_outputs.json"
    for d in (lay.root, lay.state, lay.runs_dir, lay.backups, lay.panel_dir, lay.strategies, lay.streams, lay.resume):
        assert d.is_dir() and stat.S_IMODE(d.stat().st_mode) == 0o700

def test_whole_home_symlink_alias_resolves_to_same_root(tmp_path, monkeypatch):
    real = tmp_path / "real"; real.mkdir()
    alias = tmp_path / "alias"; os.symlink(real, alias)
    monkeypatch.setenv("WMJ_HOME", str(alias))
    assert paths.ensure_layout().root == real.resolve()

def test_ensure_layout_rejects_symlinked_subdir_before_creating_anything(tmp_path, monkeypatch):
    root = tmp_path / "h"; root.mkdir()
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir()
    os.symlink(elsewhere, root / "state")
    monkeypatch.setenv("WMJ_HOME", str(root))
    with pytest.raises(EnvError) as ei:
        paths.ensure_layout()
    assert ei.value.code == "PERMISSION_DENIED"
    assert not (elsewhere / "runs").exists() and not (root / "panel").exists()

def test_home_must_not_overlap_install_root(tmp_path, monkeypatch):
    repo_src = pathlib.Path(__file__).resolve().parents[2] / "src"
    monkeypatch.setenv("WMJ_HOME", str(repo_src))
    with pytest.raises(EnvError):
        paths.ensure_layout()

def test_home_must_not_be_inside_credential_dir(tmp_path, monkeypatch):
    fake_home = tmp_path / "fh"; (fake_home / ".ssh").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("WMJ_HOME", str(fake_home / ".ssh" / "wmj"))
    with pytest.raises(EnvError):
        paths.ensure_layout()

def test_atomic_write_sets_mode_and_replaces(tmp_path, monkeypatch):
    lay = _home(tmp_path, monkeypatch)
    target = lay.config("settings.json")
    paths.atomic_write_text(target, '{"a":1}', lay=lay)
    paths.atomic_write_text(target, '{"a":2}', lay=lay)
    assert target.read_text() == '{"a":2}'
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(lay.root.glob(".settings.json.*.tmp"))

def test_atomic_write_refuses_browser_profile_and_symlink_escape(tmp_path, monkeypatch):
    lay = _home(tmp_path, monkeypatch)
    with pytest.raises(InvalidInput) as ei:
        paths.atomic_write_text(lay.browser_profile / "Cookies", "x", lay=lay)
    assert ei.value.code == "SEMANTIC_INVALID"
    outside = tmp_path / "outside.txt"
    link = lay.panel_dir / "latest.html"
    os.symlink(outside, link)
    with pytest.raises(InvalidInput):
        paths.atomic_write_text(link, "x", lay=lay)
    assert not outside.exists()

def test_export_target_rejects_protected_and_internal_state(tmp_path, monkeypatch):
    fake_home = tmp_path / "fh"; (fake_home / ".ssh").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    lay = _home(tmp_path, monkeypatch)
    lay.browser_profile.mkdir(parents=True, exist_ok=True)
    for bad in (fake_home / ".ssh" / "x.html", lay.db_path, lay.lock_path, lay.managed_outputs_path,
                lay.config("scoring.json"), lay.browser_profile / "a.html", lay.strategies / "s.json"):
        with pytest.raises(InvalidInput) as ei:
            paths.check_export_target(bad, lay)
        assert ei.value.code == "SEMANTIC_INVALID", bad

def test_export_target_shape_rules(tmp_path, monkeypatch):
    lay = _home(tmp_path, monkeypatch)
    out = tmp_path / "out"; out.mkdir()
    assert paths.check_export_target(out / "p.html", lay) == out.resolve() / "p.html"
    os.symlink(tmp_path / "nowhere", out / "l.html")
    with pytest.raises(InvalidInput):
        paths.check_export_target(out / "l.html", lay)
    with pytest.raises(InvalidInput):
        paths.check_export_target(tmp_path / "missing-dir" / "p.html", lay)
    (out / "d.html").mkdir()
    with pytest.raises(InvalidInput):
        paths.check_export_target(out / "d.html", lay)
    written = paths.export_write_text(out / "p.html", "<html>", lay)
    assert written.read_text() == "<html>" and stat.S_IMODE(written.stat().st_mode) == 0o600

def test_managed_outputs_invalidate_only_unmodified(tmp_path, monkeypatch):
    lay = _home(tmp_path, monkeypatch)
    a = lay.panel_dir / "latest.html"; a.write_text("A")
    b = tmp_path / "custom.html"; b.write_text("B")
    paths.register_managed_output(lay, a, sha256_bytes(b"A"))
    paths.register_managed_output(lay, b, sha256_bytes(b"B"))
    paths.register_managed_output(lay, a, sha256_bytes(b"A"))          # 重复登记只保留一条
    assert len(paths.managed_outputs(lay)) == 2
    assert stat.S_IMODE(lay.managed_outputs_path.stat().st_mode) == 0o600
    b.write_text("user edited")
    preview = paths.invalidate_managed_outputs(lay, dry_run=True)
    assert preview["would_remove"] == [str(a.resolve())] and preview["kept_modified"] == [str(b.resolve())]
    assert a.exists() and len(paths.managed_outputs(lay)) == 2
    done = paths.invalidate_managed_outputs(lay, dry_run=False)
    assert done["removed"] == [str(a.resolve())] and done["kept_modified"] == [str(b.resolve())]
    assert not a.exists() and b.exists() and paths.managed_outputs(lay) == []

def test_clear_migration_backups(tmp_path, monkeypatch):
    lay = _home(tmp_path, monkeypatch)
    f = lay.backups / "pre-migrate-0002-x.sqlite3"; f.write_bytes(b"db")
    assert paths.clear_migration_backups(lay, dry_run=True)["would_remove"] == [str(f)]
    assert f.exists()
    assert paths.clear_migration_backups(lay, dry_run=False)["removed"] == [str(f)]
    assert not f.exists()
