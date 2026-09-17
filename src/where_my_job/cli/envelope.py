from __future__ import annotations
import json, sys
from dataclasses import asdict
from ..errors import WmjError, ErrorItem, EXIT_OK

ENVELOPE_SCHEMA_VERSION = 1

def build(command: str, *, status: str = "ok", exit_code: int = EXIT_OK,
          run_id: str | None = None, data: dict | None = None,
          errors: list[ErrorItem] | None = None, warnings: list[str] | None = None,
          retry: dict | None = None) -> dict:
    return {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "command": command,
        "status": status,
        "exit_code": exit_code,
        "run_id": run_id,
        "data": data or {},
        "errors": [asdict(e) for e in (errors or [])],
        "warnings": list(warnings or []),
        "retry": retry if retry is not None else {"automatic": False, "not_before": None},
    }

def from_error(command: str, err: WmjError, run_id: str | None = None,
               warnings: list[str] | None = None) -> dict:
    return build(command, status=err.status, exit_code=err.exit_code, run_id=run_id or err.run_id,
                 data=err.data, errors=err.items(), warnings=warnings, retry=err.retry)

def emit(env: dict, stream=None) -> None:
    """stdout 只写一个 JSON 对象，一行，UTF-8，不转义中文。"""
    out = stream or sys.stdout
    out.write(json.dumps(env, ensure_ascii=False, separators=(",", ":")))
    out.write("\n")
    out.flush()
