import json, os, pytest
from where_my_job.config import loader
from where_my_job.errors import InvalidInput, EnvError

def _write(tmp_path, name, content):
    p = tmp_path / name
    (p.write_bytes if isinstance(content, bytes) else p.write_text)(content)
    return p

def test_load_ok_returns_same_object(tmp_path):
    p = _write(tmp_path, "s.json", '{"schema_version":1,"timezone":"Asia/Shanghai"}')
    obj = loader.read_json_file(p)
    assert loader.validate_object("settings", obj) is obj
    assert loader.load_json_file(p, "settings") == {"schema_version": 1, "timezone": "Asia/Shanghai"}

def test_missing_schema_version_and_non_object(tmp_path):
    with pytest.raises(InvalidInput) as ei:
        loader.read_json_file(_write(tmp_path, "a.json", '{"timezone":"Asia/Shanghai"}'))
    assert ei.value.items()[0].path == "$.schema_version"
    with pytest.raises(InvalidInput):
        loader.read_json_file(_write(tmp_path, "b.json", '[1,2]'))

@pytest.mark.parametrize("text", [
    '{"schema_version":1,"page_size":NaN}',
    '{"schema_version":1,"page_size":Infinity}',
    '{"schema_version":1,"page_size":-Infinity}',
    '{"schema_version":1,"page_size":1e400}',
    '{oops',
])
def test_bad_json_and_non_finite_numbers_are_schema_invalid(tmp_path, text):
    with pytest.raises(InvalidInput) as ei:
        loader.read_json_file(_write(tmp_path, "x.json", text))
    assert ei.value.code == "SCHEMA_INVALID"

def test_depth_over_64_rejected(tmp_path):
    deep = "[" * 70 + "]" * 70
    with pytest.raises(InvalidInput):
        loader.read_json_file(_write(tmp_path, "d.json", '{"schema_version":1,"x":' + deep + '}'))
    very_deep = "[" * 100000 + "]" * 100000
    with pytest.raises(InvalidInput):
        loader.read_json_file(_write(tmp_path, "dd.json", '{"schema_version":1,"x":' + very_deep + '}'))

def test_not_utf8_missing_and_directory(tmp_path):
    with pytest.raises(InvalidInput):
        loader.read_json_file(_write(tmp_path, "g.json", b'\xff\xfe{"schema_version":1}'))
    with pytest.raises(InvalidInput):
        loader.read_json_file(tmp_path / "missing.json")
    with pytest.raises(InvalidInput):
        loader.read_json_file(tmp_path)

@pytest.mark.skipif(os.geteuid() == 0, reason="root 可读任意文件")
def test_permission_denied_is_env_error(tmp_path):
    p = _write(tmp_path, "p.json", '{"schema_version":1}')
    os.chmod(p, 0)
    try:
        with pytest.raises(EnvError) as ei:
            loader.read_json_file(p)
        assert ei.value.code == "PERMISSION_DENIED" and ei.value.exit_code == 2
    finally:
        os.chmod(p, 0o600)

def test_validate_object_collects_all_issues():
    with pytest.raises(InvalidInput) as ei:
        loader.validate_object("settings", {"schema_version": 1, "retention_days": 7, "foo": 1})
    assert {i.code for i in ei.value.items()} == {"UNSUPPORTED_SETTING", "UNKNOWN_FIELD"}
