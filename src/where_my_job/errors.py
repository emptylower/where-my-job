from __future__ import annotations
from dataclasses import dataclass

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_ENV = 2
EXIT_BLOCKED = 3
EXIT_PARTIAL = 4

@dataclass
class ErrorItem:
    code: str
    message: str
    path: str | None = None

class WmjError(Exception):
    """所有可预期失败的基类。cli 把它转成 envelope。"""
    exit_code: int = EXIT_ENV
    status: str = "error"

    def __init__(self, code: str, message: str, path: str | None = None,
                 retry: dict | None = None, data: dict | None = None, run_id: str | None = None):
        super().__init__(message)
        self.code, self.message, self.path = code, message, path
        self.retry = retry
        self.data = data or {}
        self.run_id = run_id

    def items(self) -> list[ErrorItem]:
        return [ErrorItem(self.code, self.message, self.path)]

class InvalidInput(WmjError):
    exit_code = EXIT_INVALID
    status = "invalid"

    def __init__(self, issues: list[ErrorItem] | None = None, **kw):
        first = issues[0] if issues else ErrorItem("SCHEMA_INVALID", "invalid input")
        super().__init__(first.code, first.message, first.path, **kw)
        self._issues = list(issues or [first])

    def items(self) -> list[ErrorItem]:
        return list(self._issues)

class EnvError(WmjError):
    exit_code = EXIT_ENV
    status = "error"

class Blocked(WmjError):
    exit_code = EXIT_BLOCKED
    status = "blocked"

class Partial(WmjError):
    exit_code = EXIT_PARTIAL
    status = "partial"
