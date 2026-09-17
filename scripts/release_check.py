#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile

REPO = pathlib.Path(__file__).resolve().parents[1]
PUBLIC = ("src", "skill", "tests", "scripts", "SKILL.md", "README.md", "pyproject.toml", "uv.lock", "NOTICE", "LICENSE")
SKIP = {".git", ".venv", "__pycache__", ".pytest_cache", ".omc", "dist", "build", "node_modules"}
TEXT = {".py", ".json", ".md", ".toml", ".lock", ".txt", ".html", ".js", ".css", ".sql", ".yaml", ".yml", ".cfg", ".ini"}
SPECIAL = {"LICENSE", "NOTICE", "PKG-INFO", "METADATA", "WHEEL", "RECORD", "entry_points.txt"}
PATTERNS = {
    "encrypt_job_id": re.compile(r"(?<![A-Za-z0-9])[0-9a-f]{16}[A-Za-z0-9]{12}(?![A-Za-z0-9])"),
    "lid": re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{11}\.search\.\d+\b"),
    "security_id": re.compile(r"[A-Za-z0-9_\-]{180,}~"),
    "cn_mobile": re.compile(r"(?<![A-Za-z0-9])1[3-9]\d{9}(?![A-Za-z0-9])"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
}
BOSS = re.compile(r"boss:([A-Za-z0-9~_-]+)")
ALLOWED_EMAILS = {"noreply@anthropic.com"}

def finding(kind, name):
    return {"kind": kind, "file": name, "match": "<redacted>"}

def inspect_text(name, text, private_names, strict_fixture=False):
    out = []
    for kind, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            if kind == "email" and match.group() in ALLOWED_EMAILS:
                continue
            out.append(finding(kind, name))
    for match in BOSS.finditer(text):
        token = match.group(1)
        if not token.startswith("SYN") and (strict_fixture or len(token) >= 16):
            out.append(finding("non_synthetic_job_id", name))
    for company in private_names:
        if company in text:
            out.append(finding("private_company_name", name))
    return out

def private_company_names():
    value = os.environ.get("WMJ_PRIVATE_MANIFEST")
    if not value:
        return set()
    manifest = pathlib.Path(value).expanduser().resolve()
    obj = json.loads(manifest.read_text(encoding="utf-8"))
    names = set()
    for entry in obj["files"]:
        path = pathlib.Path(entry["path"]).expanduser()
        if not path.is_absolute():
            path = manifest.parent / path
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data["jobs"]:
            name = row.get("boss_name")
            if isinstance(name, str) and len(name.strip()) >= 4:
                names.add(name.strip())
    return names

def files_under(root):
    if not root.exists() and not root.is_symlink():
        raise FileNotFoundError(root)
    if root.is_symlink():
        yield root
    elif root.is_file():
        yield root
    else:
        for parent, directories, filenames in os.walk(root):
            base = pathlib.Path(parent)
            for directory in list(directories):
                path = base / directory
                if path.is_symlink():
                    yield path
                    directories.remove(directory)
                elif directory in SKIP or path.parts[-3:] == ("tests", "fixtures", "private"):
                    directories.remove(directory)
            for filename in filenames:
                path = base / filename
                if path.suffix in TEXT or path.name in SPECIAL or path.is_symlink():
                    yield path

def scan(paths, names):
    findings, count = [], 0
    seen = set()
    for root in paths:
        for path in files_under(root):
            if path in seen:
                continue
            seen.add(path)
            name = str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)
            if path.is_symlink():
                findings.append(finding("symlink", name))
                continue
            text = path.read_text(encoding="utf-8")
            count += 1
            strict = path.suffix == ".json" and ("skill/examples/" in name or "tests/fixtures/synthetic/" in name)
            findings.extend(inspect_text(name, text, names, strict))
    return findings, count

def allowed(name, wheel):
    path = pathlib.PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        return False
    if any(part in SKIP for part in path.parts):
        return False
    if wheel:
        if name.startswith("where_my_job/"):
            return path.suffix in TEXT or path.name == "LICENSE"
        if len(path.parts) >= 2 and path.parts[0].endswith(".dist-info"):
            rest = "/".join(path.parts[1:])
            return rest in {"METADATA", "WHEEL", "RECORD", "entry_points.txt", "licenses/LICENSE", "licenses/NOTICE"}
        return False
    exact = {"SKILL.md", "README.md", "LICENSE", "NOTICE", "pyproject.toml", "uv.lock", "PKG-INFO", "scripts/release_check.py", ".gitignore"}
    return name in exact or (
        name.startswith(("src/where_my_job/", "skill/", "tests/fixtures/synthetic/"))
        and (path.suffix in TEXT or path.name == "LICENSE"))

def inspect_members(members, wheel, names):
    import configparser
    members = list(members)
    problems, filenames, content_findings = [], [], []
    for name, data, regular in members:
        filenames.append(name)
        if not regular or not allowed(name, wheel):
            problems.append(name)
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(name)
            continue
        strict = name.endswith(".json") and name.startswith(("skill/examples/", "tests/fixtures/synthetic/"))
        content_findings.extend(inspect_text(name, text, names, strict))
    required = ({"where_my_job/__init__.py", "where_my_job/cli/main.py", "where_my_job/release.py",
                 "where_my_job/vendor/boss_zhipin_scraper/LICENSE", "where_my_job/vendor/boss_zhipin_scraper/UPSTREAM.md"}
                if wheel else {"SKILL.md", "README.md", "LICENSE", "NOTICE", "pyproject.toml", "uv.lock",
                               "scripts/release_check.py", "skill/examples/report.synthetic.json"})
    if len(filenames) != len(set(filenames)):
        problems.append("duplicate archive member")
    if wheel:
        roots = {name.split("/", 1)[0] for name in filenames if ".dist-info/" in name}
        if len(roots) != 1 or not all(re.fullmatch(r"where_my_job-[^/]+\.dist-info", r) for r in roots):
            problems.append("expected one where_my_job dist-info directory")
        else:
            info = next(iter(roots))
            required |= {info + "/" + name for name in ("METADATA", "WHEEL", "RECORD", "entry_points.txt")}
            entries = {name: data for name, data, regular in members if regular}
            try:
                parser = configparser.ConfigParser(interpolation=None)
                parser.read_string(entries[info + "/entry_points.txt"].decode("utf-8"))
                if parser.get("console_scripts", "where-my-job") != "where_my_job.cli.main:main":
                    problems.append("wrong CLI entry point")
            except (KeyError, UnicodeError, configparser.Error):
                problems.append("missing or invalid CLI entry point")
    problems.extend("missing:" + p for p in sorted(required - set(filenames)))
    return filenames, problems, content_findings

def build_and_inspect(names):
    with tempfile.TemporaryDirectory(prefix="wmj-build-") as directory:
        result = subprocess.run(["uv", "build", "--offline", "--out-dir", directory],
                                cwd=REPO, capture_output=True, text=True)
        if result.returncode:
            return {"sdist_ok": False, "wheel_ok": False, "sdist_files": [], "wheel_files": [],
                    "problems": [], "findings": [], "error": "offline build failed"}
        folder = pathlib.Path(directory)
        sdists, wheels = list(folder.glob("*.tar.gz")), list(folder.glob("*.whl"))
        if len(sdists) != 1 or len(wheels) != 1:
            raise ValueError("expected exactly one sdist and one wheel")
        with tarfile.open(sdists[0]) as archive:
            rows = []
            for member in archive.getmembers():
                if member.isdir():
                    continue
                parts = pathlib.PurePosixPath(member.name).parts
                name = "/".join(parts[1:])
                regular = member.isfile() and bool(parts) and not member.name.startswith("/") and ".." not in parts
                data = archive.extractfile(member).read() if regular else b""
                rows.append((name, data, regular))
            sf, sp, sx = inspect_members(rows, False, names)
        with zipfile.ZipFile(wheels[0]) as archive:
            rows = []
            for member in archive.infolist():
                if member.is_dir():
                    continue
                mode = member.external_attr >> 16
                import stat
                regular = stat.S_IFMT(mode) in (0, stat.S_IFREG)
                rows.append((member.filename, archive.read(member), regular))
            wf, wp, wx = inspect_members(rows, True, names)
        return {"sdist_ok": not sp and not sx, "wheel_ok": not wp and not wx,
                "sdist_files": sf, "wheel_files": wf, "problems": sp + wp, "findings": sx + wx}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--extra-path", action="append", default=[])
    args = parser.parse_args()
    try:
        names = private_company_names()
        paths = [REPO / p for p in PUBLIC if (REPO / p).exists()]
        paths += [pathlib.Path(p) for p in args.extra_path]
        findings, count = scan(paths, names)
        build = None if args.no_build else build_and_inspect(names)
        if build:
            findings += build["findings"]
        code = 1 if findings or (build and build["problems"]) else 0
        if build and build.get("error"):
            code = 2
        print(json.dumps({"scanned_files": count, "findings": findings, "build": build}, ensure_ascii=False))
        return code
    except (OSError, ValueError, KeyError, tarfile.TarError, zipfile.BadZipFile):
        print(json.dumps({"scanned_files": 0, "findings": [], "build": None,
                          "error": "release inspection failed; no clean result claimed"}))
        return 2

if __name__ == "__main__":
    sys.exit(main())
