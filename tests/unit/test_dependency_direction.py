import pathlib, re
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "where_my_job"

def _imports(path: pathlib.Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"^\s*(?:from|import)\s+([\w\.]+)", text, re.M))

def test_only_store_imports_sqlite3():
    for p in SRC.rglob("*.py"):
        rel = p.relative_to(SRC).as_posix()
        if rel.startswith("store/"):
            continue
        assert "sqlite3" not in _imports(p), f"{rel} imports sqlite3"

def test_pure_packages_do_not_import_io_layers():
    banned = {"where_my_job.store", "where_my_job.policy", "where_my_job.adapter", "where_my_job.launcher",
              "where_my_job.service", "..store", "..policy", "..adapter", "..launcher", "..service",
              "sqlite3", "websocket", "subprocess"}
    for pkg in ("rules", "normalize", "validate", "streams"):
        for p in (SRC / pkg).rglob("*.py"):
            imps = _imports(p)
            assert not (imps & banned), f"{p.relative_to(SRC)} imports {imps & banned}"
    jsonsafe = SRC / "config" / "jsonsafe.py"
    if jsonsafe.exists():
        assert not (_imports(jsonsafe) & banned)

def test_no_llm_sdk_dependency():
    data = tomllib.loads((SRC.parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    deps = " ".join(data["project"]["dependencies"]).lower()
    for bad in ("anthropic", "openai", "langchain", "litellm"):
        assert bad not in deps

def test_psutil_only_in_launcher():
    for p in SRC.rglob("*.py"):
        rel = p.relative_to(SRC).as_posix()
        if rel.startswith("launcher/"):
            continue
        assert "psutil" not in _imports(p), f"{rel} imports psutil"
