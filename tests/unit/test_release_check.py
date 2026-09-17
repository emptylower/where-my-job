# tests/unit/test_release_check.py
import json, os, pathlib, subprocess, sys
import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "release_check.py"

def _run(*args, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=str(REPO), capture_output=True, text=True, env=env)

def test_scan_public_tree_passes():
    r = _run("--no-build")
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(r.stdout)
    assert report["findings"] == [] and report["scanned_files"] > 20 and report["build"] is None

def test_scan_detects_real_looking_ids_and_pii(tmp_path):
    bad = tmp_path / "leak.json"
    job_token = ("ab" * 8) + ("X9" * 6)
    bad.write_text(json.dumps({
        "encrypt_job_id": job_token,
        "lid": ("Q" * 11) + ".search." + str(4),
        "securityId": "A" * 210 + "~",
        "phone": str(13 * 10**9 + 812345678),
        "mail": "someone" + "@" + "example.com",
        "job": "boss:" + job_token,
    }), encoding="utf-8")
    r = _run("--no-build", "--extra-path", str(bad))
    assert r.returncode == 1
    findings = json.loads(r.stdout)["findings"]
    kinds = {f["kind"] for f in findings}
    assert {"encrypt_job_id", "lid", "security_id", "cn_mobile", "email", "non_synthetic_job_id"} <= kinds
    assert all(f["match"] == "<redacted>" for f in findings)
    assert job_token not in r.stdout

def test_private_manifest_names_are_checked_when_available(tmp_path):
    man = tmp_path / "m.json"; data = tmp_path / "x_y.json"
    data.write_text(json.dumps({"keyword": "y", "city": "x", "scraped_at": "2026-09-14T11:00:00",
                                "jobs": [{"boss_name": "某真实公司名称示例", "encrypt_job_id": "zzz"}]}), encoding="utf-8")
    man.write_text(json.dumps({"schema_version": 1, "files": [{"path": str(data)}]}), encoding="utf-8")
    leak = tmp_path / "leak.md"; leak.write_text("这里提到了 某真实公司名称示例 的岗位", encoding="utf-8")
    r = _run("--no-build", "--extra-path", str(leak), env={**os.environ, "WMJ_PRIVATE_MANIFEST": str(man)})
    assert r.returncode == 1
    assert any(f["kind"] == "private_company_name" for f in json.loads(r.stdout)["findings"])

@pytest.mark.slow
def test_offline_build_artifacts_pass_member_and_content_checks():
    r = _run()
    assert r.returncode == 0, r.stdout + r.stderr
    build = json.loads(r.stdout)["build"]
    assert build["sdist_ok"] and build["wheel_ok"] and build["problems"] == [] and build["findings"] == []
    sdist = build["sdist_files"]
    assert "SKILL.md" in sdist and "uv.lock" in sdist and "skill/examples/report.synthetic.json" in sdist
    assert not any(p.startswith(("tests/fixtures/private", "docs/")) for p in sdist)
    assert any(p.endswith(".dist-info/entry_points.txt") for p in build["wheel_files"])
