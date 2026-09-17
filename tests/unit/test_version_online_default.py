# tests/unit/test_version_online_default.py
from where_my_job import release
from where_my_job.service.version_cmd import build_id

def test_version_reports_online_adapter_release_default(cli, monkeypatch):
    rc, env, _ = cli(["version"])
    assert rc == 0 and env["data"]["online_adapter_default"] == release.ONLINE_ADAPTER_DEFAULT
    monkeypatch.setattr(release, "ONLINE_ADAPTER_DEFAULT", "enabled")
    rc, env, _ = cli(["version"])
    assert rc == 0 and env["data"] == {"version": env["data"]["version"], "build_id": build_id(),
                                       "online_adapter_default": "enabled"}

def test_build_id_is_the_only_way_to_tell_two_builds_apart(cli, monkeypatch, tmp_path):
    """版本号常年 0.1.0：两份不同代码的 `version` 输出原本一字不差。
    build_id 必须随包内文件内容变，否则"确认装的是哪份代码"仍然无从确认。"""
    import hashlib, pathlib as _p, where_my_job.service.version_cmd as vc
    rc, env, _ = cli(["version"])
    before = env["data"]["build_id"]
    real_read = _p.Path.read_bytes
    target = _p.Path(vc.__file__).resolve().parent.parent / "clock.py"

    def poisoned(self):                                   # 只改一个包内文件的内容，路径集合不变
        return b"# changed\n" + real_read(self) if self == target else real_read(self)

    monkeypatch.setattr(_p.Path, "read_bytes", poisoned)
    rc, env, _ = cli(["version"])
    assert rc == 0 and env["data"]["build_id"] != before
