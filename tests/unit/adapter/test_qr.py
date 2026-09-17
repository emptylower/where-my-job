# tests/unit/adapter/test_qr.py
import io, re
import segno, zxingcpp
from PIL import Image
from where_my_job.adapter import qr

LOGIN = b"https://example.invalid/login?uuid=SYN-LOGIN-A"
OTHER = b"https://example.invalid/app?from=SYN-DOWNLOAD"

def _qr_image(payload: bytes, scale: int) -> Image.Image:
    buf = io.BytesIO()
    segno.make_qr(payload, error="m").save(buf, kind="png", scale=scale, border=4)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")

def _page(*codes) -> bytes:
    page = Image.new("RGB", (1280, 800), (245, 246, 248))
    for payload, scale, pos in codes:
        page.paste(_qr_image(payload, scale), pos)
    out = io.BytesIO()
    page.save(out, format="PNG")
    return out.getvalue()

def _decode_rendered(text: str) -> list[bytes]:
    """把终端半块字符还原成黑白像素图再识别，证明重绘结果可扫。"""
    rows = []
    for line in text.split("\n"):
        plain = re.sub(r"\x1b\[[0-9;]*m", "", line)
        rows.append([ch in "█▀" for ch in plain])
        rows.append([ch in "█▄" for ch in plain])
    scale = 8
    img = Image.new("L", (len(rows[0]) * scale, len(rows) * scale), 255)
    for y, row in enumerate(rows):
        for x, dark in enumerate(row):
            if dark:
                img.paste(0, (x * scale, y * scale, (x + 1) * scale, (y + 1) * scale))
    return [bytes(c.bytes) for c in zxingcpp.read_barcodes(img, formats=zxingcpp.BarcodeFormat.QRCode)]

def test_finds_login_code_in_page_screenshot():
    hits = qr.find_qr_codes(_page((LOGIN, 6, (600, 200))))
    assert [h.payload for h in hits] == [LOGIN]

def test_largest_code_first_when_page_shows_several():
    hits = qr.find_qr_codes(_page((OTHER, 2, (80, 650)), (LOGIN, 6, (600, 200))))
    assert [h.payload for h in hits] == [LOGIN, OTHER]
    assert hits[0].area > hits[1].area

def test_blank_and_corrupt_images_yield_nothing():
    blank = io.BytesIO()
    Image.new("RGB", (300, 300), "white").save(blank, format="PNG")
    assert qr.find_qr_codes(blank.getvalue()) == []
    assert qr.find_qr_codes(b"not a png") == []

def test_png_bytes_round_trip():
    assert [h.payload for h in qr.find_qr_codes(qr.png_bytes(LOGIN))] == [LOGIN]

def test_terminal_rendering_is_scannable_black_on_white_and_hides_text():
    text = qr.render_terminal(LOGIN)
    lines = text.split("\n")
    assert all(line.startswith("\x1b[30;107m") and line.endswith("\x1b[0m") for line in lines)
    assert _decode_rendered(text) == [LOGIN]
    assert "example.invalid" not in text and "SYN-LOGIN-A" not in text

def test_digest_is_stable_and_not_the_payload():
    digest = qr.payload_digest(LOGIN)
    assert digest == qr.payload_digest(LOGIN) and len(digest) == 64 and "SYN" not in digest

def test_text_lines_scan_on_dark_background_without_control_codes():
    from tests.helpers.qr_text import decode_lines
    lines = qr.text_lines(LOGIN)
    assert decode_lines(lines) == LOGIN
    assert decode_lines(lines, light_terminal=True) != LOGIN
    joined = "".join(lines)
    assert "\x1b" not in joined and set(joined) <= set("█▀▄ ")
    assert len({len(line) for line in lines}) == 1
    assert "example.invalid" not in joined and "SYN-LOGIN-A" not in joined

def test_text_lines_light_terminal_variant_scans_on_light_background():
    from tests.helpers.qr_text import decode_lines
    lines = qr.text_lines(LOGIN, light_terminal=True)
    assert decode_lines(lines, light_terminal=True) == LOGIN
    assert decode_lines(lines) != LOGIN
