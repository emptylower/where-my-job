from __future__ import annotations
import re

def split_list(text: str | None, sep: str = r"\s*\|\s*") -> tuple[str, ...]:
    out: list[str] = []
    for s in re.split(sep, text or ""):
        s = s.strip()
        if s and s not in out:
            out.append(s)
    return tuple(out)
