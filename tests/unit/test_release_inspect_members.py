# tests/unit/test_release_inspect_members.py
"""纯内存检查 inspect_members：合法清单通过；路径、成员类型、必要文件、入口点或内容任一不合格即失败。"""
import importlib.util, json, pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("release_check", REPO / "scripts" / "release_check.py")
release_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_check)

INFO = "where_my_job-0.1.0.dist-info"

def _token() -> str:
    return ("cd" * 8) + ("Z7" * 6)

def _sdist_ok() -> list:
    return [
        ("SKILL.md", b"# skill\n", True),
        ("README.md", b"# readme\n", True),
        ("LICENSE", b"MIT\n", True),
        ("NOTICE", b"notice\n", True),
        ("pyproject.toml", b"[project]\nname = 'where-my-job'\n", True),
        ("uv.lock", b"version = 1\n", True),
        ("PKG-INFO", b"Metadata-Version: 2.3\n", True),
        ("scripts/release_check.py", b"print('ok')\n", True),
        ("skill/examples/report.synthetic.json", json.dumps({"job_id": "boss:SYN0001aaaa"}).encode(), True),
        ("src/where_my_job/__init__.py", b"__version__ = '0.1.0'\n", True),
    ]

def _wheel_ok() -> list:
    return [
        ("where_my_job/__init__.py", b"__version__ = '0.1.0'\n", True),
        ("where_my_job/cli/main.py", b"def main():\n    return 0\n", True),
        ("where_my_job/release.py", b'ONLINE_ADAPTER_DEFAULT = "disabled"\n', True),
        ("where_my_job/vendor/boss_zhipin_scraper/LICENSE", b"MIT\n", True),
        ("where_my_job/vendor/boss_zhipin_scraper/UPSTREAM.md", b"# upstream\n", True),
        (f"{INFO}/METADATA", b"Name: where-my-job\n", True),
        (f"{INFO}/WHEEL", b"Wheel-Version: 1.0\n", True),
        (f"{INFO}/RECORD", b"", True),
        (f"{INFO}/entry_points.txt", b"[console_scripts]\nwhere-my-job = where_my_job.cli.main:main\n", True),
    ]

def test_complete_synthetic_sdist_passes():
    _, problems, findings = release_check.inspect_members(_sdist_ok(), False, set())
    assert problems == [] and findings == []

def test_complete_wheel_passes():
    _, problems, findings = release_check.inspect_members(_wheel_ok(), True, set())
    assert problems == [] and findings == []

def test_real_style_id_inside_allowed_path_fails():
    rows = [r for r in _sdist_ok() if r[0] != "skill/examples/report.synthetic.json"]
    rows.append(("skill/examples/report.synthetic.json", json.dumps({"job_id": "boss:" + _token()}).encode(), True))
    _, problems, findings = release_check.inspect_members(rows, False, set())
    kinds = {f["kind"] for f in findings}
    assert problems == [] and {"non_synthetic_job_id", "encrypt_job_id"} <= kinds
    assert all(f["match"] == "<redacted>" for f in findings)

def test_unknown_top_level_file_fails():
    _, problems, _ = release_check.inspect_members(_sdist_ok() + [("notes.txt", b"x", True)], False, set())
    assert "notes.txt" in problems

def test_non_regular_member_fails():
    _, problems, _ = release_check.inspect_members(_sdist_ok() + [("skill/link.md", b"", False)], False, set())
    assert "skill/link.md" in problems

def test_path_traversal_fails():
    _, problems, _ = release_check.inspect_members(_sdist_ok() + [("../evil.py", b"", True)], False, set())
    assert "../evil.py" in problems

def test_missing_skill_md_fails():
    rows = [r for r in _sdist_ok() if r[0] != "SKILL.md"]
    _, problems, _ = release_check.inspect_members(rows, False, set())
    assert "missing:SKILL.md" in problems

def test_wheel_missing_vendor_license_fails():
    rows = [r for r in _wheel_ok() if not r[0].endswith("boss_zhipin_scraper/LICENSE")]
    _, problems, _ = release_check.inspect_members(rows, True, set())
    assert "missing:where_my_job/vendor/boss_zhipin_scraper/LICENSE" in problems

def test_wheel_wrong_entry_point_fails():
    rows = [r for r in _wheel_ok() if not r[0].endswith("entry_points.txt")]
    rows.append((f"{INFO}/entry_points.txt", b"[console_scripts]\nwhere-my-job = somewhere:main\n", True))
    _, problems, _ = release_check.inspect_members(rows, True, set())
    assert "wrong CLI entry point" in problems

def test_private_company_name_inside_member_fails():
    rows = [r for r in _sdist_ok() if r[0] != "README.md"]
    rows.append(("README.md", "提到 某真实公司名称示例".encode("utf-8"), True))
    _, _, findings = release_check.inspect_members(rows, False, {"某真实公司名称示例"})
    assert any(f["kind"] == "private_company_name" for f in findings)

def test_inspect_text_ignores_hex_hash_digits():
    """协调人修订：cn_mobile 前后断言为非字母数字；uv.lock 哈希中的数字串不误报，真实手机号仍命中。"""
    import importlib.util as _u
    spec = _u.spec_from_file_location("release_check_hex", REPO / "scripts" / "release_check.py")
    rc = _u.module_from_spec(spec); spec.loader.exec_module(rc)
    phone = "1" + "38" + "12345678"
    assert [f for f in rc.inspect_text("uv.lock", "sha256:ab" + phone + "cd", set()) if f["kind"] == "cn_mobile"] == []
    assert [f for f in rc.inspect_text("x.md", "电话 " + phone + "。", set()) if f["kind"] == "cn_mobile"] != []
