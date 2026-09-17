from where_my_job.errors import (InvalidInput, EnvError, Blocked, Partial,
                                 ErrorItem, EXIT_INVALID, EXIT_ENV, EXIT_BLOCKED, EXIT_PARTIAL)

def test_exit_codes_and_status():
    assert InvalidInput([ErrorItem("SCHEMA_INVALID", "x", "$.a")]).exit_code == EXIT_INVALID
    assert EnvError("CDP_UNAVAILABLE", "no chrome").exit_code == EXIT_ENV
    assert Blocked("RISK_DETECTED", "31").exit_code == EXIT_BLOCKED
    assert Partial("PARTIAL_RESULT", "1/2").exit_code == EXIT_PARTIAL
    assert Blocked("COOLDOWN_ACTIVE", "wait").status == "blocked"

def test_invalid_input_keeps_all_issues():
    e = InvalidInput([ErrorItem("SCHEMA_INVALID", "a", "$.a"), ErrorItem("UNKNOWN_FIELD", "b", "$.b")])
    assert [i.code for i in e.items()] == ["SCHEMA_INVALID", "UNKNOWN_FIELD"]
    assert e.path == "$.a"

def test_wmj_error_carries_retry_data_and_run_id():
    e = Blocked("COOLDOWN_ACTIVE", "x", retry={"automatic": False, "not_before": "2026-09-15T00:00:00.000000Z"},
                data={"saved": 3}, run_id="run_1")
    assert e.retry["not_before"].endswith("Z") and e.data == {"saved": 3} and e.run_id == "run_1"
    e2 = InvalidInput([ErrorItem("SCHEMA_INVALID", "x")], run_id="run_2")
    assert e2.run_id == "run_2"
