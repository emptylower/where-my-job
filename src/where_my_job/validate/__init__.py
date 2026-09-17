from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class Issue:
    code: str          # SCHEMA_INVALID / SEMANTIC_INVALID / UNKNOWN_FIELD / UNSUPPORTED_SETTING
    path: str          # "$.searches[0].pages"
    message: str

@dataclass(frozen=True)
class Facts:
    """service 提供给校验器的数据库事实快照；validate 不自己查库。"""
    job_ids: frozenset[str] = frozenset()
    evidence_ids_by_job: dict[str, frozenset[str]] | None = None
    bundle_ids_by_job: dict[str, frozenset[str]] | None = None
    active_streams: dict[str, dict] | None = None
    application_ids_by_job: dict[str, frozenset[str]] | None = None

    @property
    def injected(self) -> bool:
        """任一 *_by_job 字段不为 None 即视为已由数据库注入。"""
        return any(v is not None for v in (self.evidence_ids_by_job, self.bundle_ids_by_job,
                                           self.application_ids_by_job))

KINDS = ("profile", "strategy", "scoring", "panel", "evidence", "report",
         "event", "stream", "settings", "import_manifest")

def validate(kind: str, obj: Any, facts: Facts | None = None) -> list[Issue]:
    """先 JSON Schema，再语义；返回空列表即通过。"""
    from .schema import schema_issues
    issues = schema_issues(kind, obj)
    if issues:
        return issues
    from importlib import import_module
    mod = import_module(f".semantic.{kind}", __package__)
    return mod.check(obj, facts or Facts())
