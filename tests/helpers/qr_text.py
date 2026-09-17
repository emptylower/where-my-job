# tests/helpers/qr_text.py
"""把半块字符二维码按终端配色还原成图片再识别，模拟用户用手机扫 agent 命令输出里的二维码。
识别时关闭反色尝试：深浅背景画反了会被测出来。"""
from __future__ import annotations
import zxingcpp
from PIL import Image

BLOCK_CHARS = frozenset("█▀▄ ")

def lines_to_image(lines: list[str], *, light_terminal: bool = False, scale: int = 8, margin: int = 6) -> Image.Image:
    """字符笔画用终端前景色，其余用背景色；图片外圈也是背景色，和真实终端一样。"""
    fg, bg = (0, 255) if light_terminal else (255, 0)
    rows = []
    for line in lines:
        rows.append([ch in "█▀" for ch in line])
        rows.append([ch in "█▄" for ch in line])
    width = max(len(row) for row in rows)
    image = Image.new("L", ((width + 2 * margin) * scale, (len(rows) + 2 * margin) * scale), bg)
    for y, row in enumerate(rows):
        for x, ink in enumerate(row):
            if ink:
                image.paste(fg, ((x + margin) * scale, (y + margin) * scale,
                                 (x + margin + 1) * scale, (y + margin + 1) * scale))
    return image

def decode_lines(lines: list[str], *, light_terminal: bool = False) -> bytes | None:
    image = lines_to_image(lines, light_terminal=light_terminal)
    hits = [code for code in zxingcpp.read_barcodes(image, formats=zxingcpp.BarcodeFormat.QRCode, try_invert=False)
            if code.valid]
    return bytes(hits[0].bytes) if hits else None

def drawings(stderr_text: str, caption: str) -> list[list[str]]:
    """stderr 里每个提示行之后紧跟的连续半块字符行。"""
    lines = stderr_text.split("\n")
    out = []
    for i, line in enumerate(lines):
        if line != caption:
            continue
        block = []
        for nxt in lines[i + 1:]:
            if not nxt or not set(nxt) <= BLOCK_CHARS:
                break
            block.append(nxt)
        out.append(block)
    return out
