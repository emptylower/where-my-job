import io, json
from where_my_job.cli import envelope
from where_my_job.errors import Blocked

def test_build_defaults():
    env = envelope.build("status", data={"x": 1})
    assert env["schema_version"] == 1 and env["status"] == "ok" and env["exit_code"] == 0
    assert env["errors"] == [] and env["warnings"] == [] and env["run_id"] is None
    assert env["retry"] == {"automatic": False, "not_before": None}

def test_from_error_maps_fields_and_run_id_from_error():
    err = Blocked("RISK_DETECTED", "检测到限制访问", path="tasks[1]",
                  retry={"automatic": False, "not_before": "2026-09-15T00:00:00.000000Z"},
                  data={"saved_jobs": 30}, run_id="run_x")
    env = envelope.from_error("scan", err)
    assert env["status"] == "blocked" and env["exit_code"] == 3
    assert env["errors"] == [{"code": "RISK_DETECTED", "message": "检测到限制访问", "path": "tasks[1]"}]
    assert env["data"] == {"saved_jobs": 30} and env["run_id"] == "run_x"

def test_emit_single_line_utf8():
    buf = io.StringIO()
    envelope.emit(envelope.build("status", data={"名": "值"}), stream=buf)
    s = buf.getvalue()
    assert s.count("\n") == 1 and json.loads(s)["data"] == {"名": "值"} and "\\u" not in s
