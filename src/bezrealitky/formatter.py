# bez_formatter.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from datetime import datetime
from typing import List, Dict, Any, Iterable


NBSP = "\u00A0"

def _fmt_int(x) -> str | None:
    if x is None:
        return None
    try:
        return f"{int(x):,}".replace(",", " ")
    except Exception:
        return None

def _fmt_float(x, nd=1) -> str | None:
    if x is None:
        return None
    try:
        v = float(x)
        s = f"{v:.{nd}f}".rstrip("0").rstrip(".")
        return s.replace(",", " ").replace(".", ",")  # CZ styl: desetinná čárka
    except Exception:
        return None

def _coerce_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple, set)):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v).strip()
    if not s:
        return []
    # pokus: rozdělít podle "•", "," nebo " · "
    if "•" in s:
        parts = [p.strip() for p in s.split("•")]
    elif " · " in s:
        parts = [p.strip() for p in s.split(" · ")]
    else:
        parts = [p.strip() for p in s.split(",")]
    return [p for p in parts if p]


NBSP = "\u00A0"


def build_listing_blocks_bez(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Postaví Slack bloky pro Bezrealitky:
      1) *Adresa nebo title* — CENA Kč
      2) :couch_and_lamp: dispo · :triangular_ruler: XX m²
      3) (volitelně) :bookmark_tabs: features
      4) (volitelně) Y Kč/m²
      5) :link: Otevřít na Bezrealitky
    """
    blocks: List[Dict[str, Any]] = []

    for it in items:
        # základní pole
        title = it.get("title")
        address = it.get("address")
        dispo = it.get("dispo")
        area = it.get("area_m2")
        price = it.get("price_czk")
        ppm2 = it.get("price_per_m2")
        url = it.get("url")
        features = it.get("features") or []

        # co použít jako hlavní název
        main_title = address or title or url or "Bez názvu"

        # formátování čísel
        price_txt = _fmt_int(price)
        area_txt = None
        if isinstance(area, (int, float)) and area > 0:
            area_txt = f"{int(area)}{NBSP}m²"

        ppm2_txt = _fmt_int(ppm2)

        # 1) první řádek: název + cena
        if price_txt:
            line1 = f"*{main_title}* — {price_txt}{NBSP}Kč"
        else:
            line1 = f"*{main_title}*"

        # 2) druhý řádek: dispo + m²
        meta_parts: List[str] = []
        if dispo:
            meta_parts.append(f":couch_and_lamp: {dispo}")
        if area_txt:
            meta_parts.append(f":triangular_ruler: {area_txt}")
        meta_line = " · ".join(meta_parts) if meta_parts else None

        # 3) amenities (features)
        amen_line = None
        if isinstance(features, list) and features:
            # vezmeme prvních pár, ať to není kilometr dlouhé
            amen_line = ", ".join(str(f) for f in features[:6])

        # 4) skládání textu sekce
        text_lines: List[str] = [line1]
        if meta_line:
            text_lines.append(meta_line)
        if amen_line:
            text_lines.append(f":bookmark_tabs: {amen_line}")
        if ppm2_txt:
            text_lines.append(f"{ppm2_txt}{NBSP}Kč/m²")
        if url:
            text_lines.append(f":link: <{url}|Otevřít na Bezrealitky>")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(text_lines)
            },
        })
        blocks.append({"type": "divider"})

    return blocks