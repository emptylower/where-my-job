from __future__ import annotations
from dataclasses import dataclass, field
from typing import BinaryIO, TextIO
from ..clock import Clock
from ..paths import Layout
from ..store.db import Connection

@dataclass
class Context:
    home: Layout
    clock: Clock
    conn: Connection
    warnings: list[str] = field(default_factory=list)
    run_locks: dict[str, BinaryIO] = field(default_factory=dict)
    stderr: TextIO | None = None

    def log(self, msg: str) -> None:
        if self.stderr is not None:
            self.stderr.write(msg + "\n")
