# tests/regression/conftest.py
import os, pathlib, pytest

@pytest.fixture(scope="session")
def private_manifest():
    p = os.environ.get("WMJ_PRIVATE_MANIFEST")
    if not p:
        pytest.skip("WMJ_PRIVATE_MANIFEST 未设置，跳过私有回归")
    path = pathlib.Path(p).expanduser()
    assert path.exists(), f"WMJ_PRIVATE_MANIFEST 指向的文件不存在: {path}"
    return str(path)
