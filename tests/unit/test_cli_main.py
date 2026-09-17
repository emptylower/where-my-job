import json
from where_my_job.cli.main import main

def test_version_command_emits_envelope(capsys):
    rc = main(["version"])
    env = json.loads(capsys.readouterr().out)
    assert rc == 0 and env["command"] == "version" and env["data"]["version"] == "0.1.0"

def test_unknown_command_is_exit_1_with_envelope(capsys):
    rc = main(["nope"])
    env = json.loads(capsys.readouterr().out)
    assert rc == 1 and env["status"] == "invalid" and env["errors"][0]["code"] == "SCHEMA_INVALID"
