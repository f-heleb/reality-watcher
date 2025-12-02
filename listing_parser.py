# listing_parser.py
from __future__ import annotations
import re
from typing import Dict, Any, Optional
from sreality_parser import fetch_listing_description
# Řádky vypadají takto:
#
# *Prodej bytu 2+kk 48 m² Farkašova, Praha - Kyje 8 200 000 Kč* — 8 200 000 Kč
# :round_pushpin: Farkašova, Praha - Kyje · :couch_and_lamp: 2+kk
# :triangular_ruler: 48.0 m² | 170 833 Kč/m²
# :link: <https://www.sreality.cz/detail/...|Open on Sreality>

TITLE_RE    = re.compile(r"^\*(?P<title>.+?)\*", re.MULTILINE)
PRICE_RE    = re.compile(r"—\s*([\d\s\u00A0]+)\s*Kč")
LOCALITY_RE = re.compile(r":round_pushpin:\s*(.+?)(?:\s*·|\n|$)")
LAYOUT_RE   = re.compile(r":couch_and_lamp:\s*([^\n]+)")
AREA_RE     = re.compile(r":triangular_ruler:\s*([\d.,\u00A0\s]+)\s*m²")
PPM2_RE     = re.compile(r"\|\s*([\d.,\u00A0\s]+)\s*Kč/m²")


def _parse_int(num_str: Optional[str]) -> Optional[int]:
    if not num_str:
        return None
    s = num_str.replace("\u00A0", "").replace(" ", "")
    try:
        return int(float(s))
    except Exception:
        return None

def _parse_float(num_str: Optional[str]) -> Optional[float]:
    if not num_str:
        return None
    s = num_str.replace("\u00A0", "").replace(" ", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None

def _extract_first(pattern: re.Pattern, text: str) -> Optional[str]:
    m = pattern.search(text)
    return m.group(1) if m else None

def _extract_title(text: str) -> Optional[str]:
    m = TITLE_RE.search(text)
    if not m:
        return None
    return m.group("title").strip()


def build_listing_from_url(url: str, message_text: str) -> Dict[str, Any]:
    text = message_text or ""

    # ... tvoje současné parsování ze Slacku ...
    title      = _extract_title(text)
    price_str  = _extract_first(PRICE_RE, text)
    locality   = _extract_first(LOCALITY_RE, text)
    layout_str = _extract_first(LAYOUT_RE, text)
    area_str   = _extract_first(AREA_RE, text)
    ppm2_str   = _extract_first(PPM2_RE, text)
    fees_str   = _extract_first(FEES_RE, text) if "FEES_RE" in globals() else None

    price = _parse_int(price_str)
    area  = _parse_float(area_str)
    ppm2  = _parse_int(ppm2_str)
    fees  = _parse_int(fees_str)

    # 1) zkus stáhnout dlouhý popis z detailu
    try:
        long_desc = fetch_listing_description(url)
    except Exception as e:
        print("fetch_listing_description failed:", e)
        long_desc = None

    listing: Dict[str, Any] = {
        "url": url,
        "title": title or url,
        "price": price,
        "fees": fees,
        "electricity": None,
        "type": "byt",
        "ownership": None,
        "layout": layout_str,
        "area_m2": area,
        "floor": None,
        "total_floors": None,
        "building_type": None,
        "condition": None,
        "year_built": None,
        "balcony_m2": None,
        "orientation": None,
        "location": locality,
        # TADY JE KLÍČ:
        "description": long_desc,      # dlouhý popis z detailu
        "raw_text": text,              # Slackový „preview“ pro doplnění
        "local_stats": None,
    }

    return listing