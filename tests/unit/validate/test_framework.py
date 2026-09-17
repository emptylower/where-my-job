from where_my_job.validate import validate

def test_settings_ok():
    assert validate("settings", {"schema_version": 1, "timezone": "Asia/Shanghai"}) == []

def test_settings_unknown_field_and_retention_days():
    issues = validate("settings", {"schema_version": 1, "retention_days": 30, "foo": 1})
    by_path = {i.path: i.code for i in issues}
    assert by_path["$.retention_days"] == "UNSUPPORTED_SETTING" and by_path["$.foo"] == "UNKNOWN_FIELD"

def test_settings_bad_timezone():
    issues = validate("settings", {"schema_version": 1, "timezone": "Mars/Olympus"})
    assert issues[0].code == "SEMANTIC_INVALID" and issues[0].path == "$.timezone"

def test_facts_injection_rule():
    from where_my_job.validate import Facts
    assert Facts().job_ids == frozenset() and Facts().injected is False
    assert Facts(job_ids=frozenset({"boss:SYN1"})).injected is False
    assert Facts(application_ids_by_job={}).injected is True
    assert Facts(evidence_ids_by_job={"boss:SYN1": frozenset()}).injected is True

def test_import_manifest_requires_files_and_valid_timezone():
    assert validate("import_manifest", {"schema_version": 1, "files": []})[0].path == "$.files"
    issues = validate("import_manifest", {"schema_version": 1, "timezone_assumption": "Nowhere/X",
                                          "files": [{"path": "a.json"}]})
    assert issues[0].path == "$.timezone_assumption" and issues[0].code == "SEMANTIC_INVALID"
