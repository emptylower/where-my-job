from __future__ import annotations

def parse_location(text: str | None) -> tuple[str | None, str | None]:
    parts = [p.strip() for p in (text or "").split("·")]
    city = parts[0] if parts and parts[0] else None
    district = parts[1] if len(parts) > 1 and parts[1] else None
    return city, district
