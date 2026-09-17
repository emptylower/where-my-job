# src/where_my_job/panel/icons.py
"""面板用的内联图标。CSP 只允许 img-src data:，安全用例还禁止 <img>/外链，所以图标一律内联 svg：
不额外请求、不引入外部字体，颜色跟随 currentColor。这里全是常量，不含任何业务数据。"""
from __future__ import annotations

_PATHS = {
    "bars":   '<path d="M3.4 12.8V8.6M8 12.8V3.2M12.6 12.8V6.4"/>',
    "clock":  '<circle cx="8" cy="8" r="6"/><path d="M8 4.7V8l2.3 1.5"/>',
    "layers": '<path d="M8 2.4 14 5.5 8 8.6 2 5.5z"/><path d="M2.6 8.7 8 11.5l5.4-2.8"/>',
    "cap":    '<path d="M8 3 14.6 6 8 9 1.4 6z"/><path d="M4.4 7.4v3.2c0 .9 1.6 1.8 3.6 1.8s3.6-.9 3.6-1.8V7.4"/>',
    "eye":    '<path d="M1.5 8S4.4 3.9 8 3.9 14.5 8 14.5 8 11.6 12.1 8 12.1 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="1.9"/>',
    "hash":   '<path d="M6.2 2.6 4.8 13.4M11.2 2.6 9.8 13.4M2.6 5.8h11M2.4 10.2h11"/>',
    "alert":  '<path d="M8 2.6 14.6 13.4H1.4z"/><path d="M8 6.5v3.2M8 11.4v.7"/>',
    "list":   '<path d="M2.6 4.3h10.8M2.6 8h10.8M2.6 11.7h10.8"/>',
    "minus":  '<circle cx="8" cy="8" r="6"/><path d="M5.4 8h5.2"/>',
    "trend":  '<path d="M2 11.4 6 6.5l3 2.6 5-5.7"/>',
    "case":   '<path d="M3.6 5.3h8.8c.9 0 1.6.7 1.6 1.6v4.9c0 .9-.7 1.6-1.6 1.6H3.6c-.9 0-1.6-.7-1.6-1.6V6.9c0-.9.7-1.6 1.6-1.6z"/><path d="M6 5.3V4.2c0-.7.6-1.3 1.3-1.3h1.4c.7 0 1.3.6 1.3 1.3v1.1"/>',
    "target": '<circle cx="8" cy="8" r="6"/><circle cx="8" cy="8" r="2.4"/>',
    "search": '<circle cx="7.1" cy="7.1" r="4.5"/><path d="M10.5 10.5 14 14"/>',
}

def icon(name: str) -> str:
    return ('<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + _PATHS[name] + "</svg>")
