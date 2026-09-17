# src/where_my_job/adapter/qr.py
"""截图里的二维码识别、PNG 重绘与半块字符重绘。纯本地计算：不联网、不读写文件、不记录二维码内容。"""
from __future__ import annotations
import hashlib, io
from dataclasses import dataclass, field
import segno
import zxingcpp
from PIL import Image

QUIET_ZONE = 4
TEXT_QUIET_ZONE = 2
PNG_SCALE = 10
_BLACK_ON_WHITE = "\x1b[30;107m"
_RESET = "\x1b[0m"
_HALF = {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}

@dataclass(frozen=True)
class QrHit:
    payload: bytes = field(repr=False)
    area: float = 0.0

def payload_digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()

def _area(position) -> float:
    pts = [position.top_left, position.top_right, position.bottom_right, position.bottom_left]
    twice = sum(a.x * b.y - b.x * a.y for a, b in zip(pts, pts[1:] + pts[:1]))
    return abs(twice) / 2.0

def find_qr_codes(png: bytes) -> list[QrHit]:
    """返回截图里全部可识别的二维码，面积从大到小；图片无法解析时返回空列表。"""
    try:
        image = Image.open(io.BytesIO(png))
        image.load()
        gray = image.convert("L")
    except Exception:                                   # noqa: BLE001 — 截图损坏按"没有二维码"处理
        return []
    hits = [QrHit(bytes(code.bytes), _area(code.position))
            for code in zxingcpp.read_barcodes(gray, formats=zxingcpp.BarcodeFormat.QRCode)
            if code.valid and code.bytes]
    return sorted(hits, key=lambda h: h.area, reverse=True)

def png_bytes(payload: bytes) -> bytes:
    """按原内容重新编码为黑码白底 PNG，供 agent 展示给用户。"""
    buf = io.BytesIO()
    segno.make_qr(payload, error="m").save(buf, kind="png", scale=PNG_SCALE, border=QUIET_ZONE)
    return buf.getvalue()

def render_terminal(payload: bytes) -> str:
    """终端半块字符：每个字符表示上下两个模块；强制黑字白底，深色主题下也不反色。"""
    matrix = [[bool(v) for v in row]
              for row in segno.make_qr(payload, error="m").matrix_iter(scale=1, border=QUIET_ZONE)]
    if len(matrix) % 2:
        matrix.append([False] * len(matrix[0]))
    return "\n".join(_BLACK_ON_WHITE + "".join(_HALF[(t, b)] for t, b in zip(top, bottom)) + _RESET
                     for top, bottom in zip(matrix[0::2], matrix[1::2]))

def text_lines(payload: bytes, *, light_terminal: bool = False) -> list[str]:
    """不带颜色控制符的半块字符二维码，供 agent 界面的命令输出区直接显示。
    默认按深色背景画：字符笔画表示浅色模块，外圈留白也画成笔画；浅色背景传 light_terminal=True，笔画表示深色模块。"""
    matrix = [[bool(v) for v in row]
              for row in segno.make_qr(payload, error="m").matrix_iter(scale=1, border=TEXT_QUIET_ZONE)]
    ink = matrix if light_terminal else [[not v for v in row] for row in matrix]
    if len(ink) % 2:
        ink.append([not light_terminal] * len(ink[0]))
    return ["".join(_HALF[(t, b)] for t, b in zip(top, bottom)) for top, bottom in zip(ink[0::2], ink[1::2])]
