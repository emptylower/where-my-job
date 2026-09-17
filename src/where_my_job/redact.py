"""诊断用的地址脱敏。顶层模块：launcher 与 adapter 都可依赖，二者之间不互相依赖。"""
from __future__ import annotations
from urllib.parse import parse_qsl, urlsplit

MAX_NOTE_LENGTH = 120

def redact_url(url: str) -> str:
    """只保留 scheme、主机、路径与查询参数名；不保留参数值、片段与凭据。用于诊断记录。"""
    try:
        p = urlsplit(url)
        names = sorted({name for name, _ in parse_qsl(p.query, keep_blank_values=True)})
    except ValueError:
        return "invalid-url"
    out = f"{p.scheme}://{p.hostname or ''}{p.path}"
    if names:
        out += "?[" + ",".join(names) + "]"
    return out[:MAX_NOTE_LENGTH]
