# -*- coding: utf-8 -*-
"""
Bezrealitky parser – robustní best-effort extrakce.
API:
- fetch_page(url, timeout=20) -> str
- normalize_search_url(url, force_first_page=True, cache_bust=True) -> str
- extract_listing_links(html, base_url, max_links=200) -> list[{id,url,title}]
- extract_new_listings(url, seen_ids, scan_limit=200, take=10) -> (new_items,total)

U každé nové položky zkusí načíst DETAIL a doplní:
  type_text, address, dispo, area_m2, price_czk, price_per_m2, features(list[str])
"""

from __future__ import annotations
import re
import time
from typing import List, Tuple, Dict, Any, Set
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

import requests
from bs4 import BeautifulSoup

DEFAULT_UA = "Mozilla/5.0 (compatible; BezWatcher/1.0)"
BASE = "https://www.bezrealitky.cz"

# na listingu chytáme jen skutečné detailové URL
DETAIL_HREF = re.compile(r"/nemovitosti-byty-domy/\d{6,}-", re.IGNORECASE)

NBSP = "\u00A0"
PRICE_RE = re.compile(r"([\d\s" + NBSP + r"]+)\s*Kč\b", re.IGNORECASE)
PPM2_RE = re.compile(r"([\d\s" + NBSP + r"]+)\s*Kč\s*/\s*m²", re.IGNORECASE)
AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m[²2]\b", re.IGNORECASE)
DISPO_RE = re.compile(r"\b(\d+\s*\+\s*(?:kk|1|2|3|4|5))\b", re.IGNORECASE)

def _clean_int(s: str | None) -> int | None:
    if not s: return None
    s = s.replace(NBSP, "").replace(" ", "").replace("\u202F", "").replace(",", "")
    try: return int(s)
    except: return None

def _clean_float(s: str | None) -> float | None:
    if not s: return None
    s = s.replace(NBSP, "").replace(" ", "").replace("\u202F", "").replace(",", ".")
    try: return float(s)
    except: return None

def fetch_page(url: str, timeout: int = 20, user_agent: str = DEFAULT_UA) -> str:
    headers = {"User-Agent": user_agent, "Accept-Language": "cs,en;q=0.8"}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text

def normalize_search_url(url: str, force_first_page: bool = True, cache_bust: bool = True) -> str:
    """Zachovej původní klíče (priceTo, estateType, …), jen případně doplň page=1 a _ts."""
    p = urlparse(url)
    q = dict(parse_qs(p.query, keep_blank_values=True))
    if force_first_page and "page" not in q:
        q["page"] = ["1"]
    if cache_bust:
        q["_ts"] = [str(int(time.time()))]
    # z plošných hodnot vyber poslední (bez ztráty názvů param)
    flat = {k: (v[-1] if isinstance(v, list) else v) for k, v in q.items()}
    return urlunparse(p._replace(query=urlencode(flat, doseq=True)))

def _abs_url(href: str, base_url: str) -> str:
    u = urljoin(base_url, href.strip())
    u = urlparse(u)._replace(fragment="").geturl()
    if "bezrealitky.cz" not in u:
        u = urljoin(BASE, u)
    return u

def _id_from_url(u: str) -> str:
    m = re.search(r"/(\d{6,})-", u)
    return m.group(1) if m else u

def extract_listing_links(html: str, base_url: str, max_links: int = 200) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "lxml")
    anchors = soup.find_all("a", href=True)
    out, seen = [], set()
    for a in anchors:
        href = a["href"]
        if not DETAIL_HREF.search(href):
            continue
        url_abs = _abs_url(href, base_url)
        key = _id_from_url(url_abs)
        if key in seen:
            continue
        seen.add(key)
        title = (a.get("title") or a.get_text(" ", strip=True) or url_abs).strip() or url_abs
        out.append({"id": key, "url": url_abs, "title": title})
        if len(out) >= max_links:
            break
    return out

# ----------------- detail parsing -----------------

def _text(soup: BeautifulSoup) -> str:
    # souhrnný plain text – pomáhá pro fallback regexy
    return soup.get_text(" ", strip=True)

def _first_text(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(" ", strip=True)
            if t:
                return t
    return None

def _features_list(soup: BeautifulSoup) -> list[str]:
    # snaž se posbírat odrážky vybavení / benefity
    feats = []
    for sel in [
        "ul li",                       # genericky
        "[class*=amenit] li",          # amenity, amenities
        "[class*=benefit] li",
        "[data-testid*=feature] li",
    ]:
        for li in soup.select(sel):
            txt = li.get_text(" ", strip=True)
            if txt and len(txt) <= 60 and txt.lower() not in [t.lower() for t in feats]:
                feats.append(txt)
        if feats:
            break
    return feats[:10]

def get_detail_fields(url: str, timeout: int = 20) -> Dict[str, Any]:
    """
    Robustní best-effort: zkusíme různá místa, jinak regex přes celý text.
    """
    try:
        h = fetch_page(url, timeout=timeout)
    except Exception:
        return {}

    soup = BeautifulSoup(h, "lxml")
    body_text = _text(soup)

    # typ nabídky (např. PRODEJ BYTU) – zkus headline / badge / breadcrumb
    type_text = _first_text(soup, [
        "h1", "header h1", "[class*=title]", "[class*=badge]", "nav.breadcrumb"
    ])
    # adresa
    address = _first_text(soup, [
        "[class*=address]", "[class*=location]", "h2", "header h2", "div[data-testid*=address]"
    ])

    # dispo & m² – buď z prominentních polí, nebo regexem
    dispo = None
    m = DISPO_RE.search(body_text)
    if m:
        dispo = m.group(1).replace(" ", "")

    area_m2 = None
    m = AREA_RE.search(body_text)
    if m:
        area_m2 = _clean_float(m.group(1))

    price_czk = None
    m = PRICE_RE.search(body_text)
    if m:
        price_czk = _clean_int(m.group(1))

    price_per_m2 = None
    m = PPM2_RE.search(body_text)
    if m:
        price_per_m2 = _clean_int(m.group(1))

    # když není ppm2 a máme price + area, dopočítáme
    if price_per_m2 is None and price_czk and area_m2 and area_m2 > 0:
        price_per_m2 = round(price_czk / area_m2)

    features = _features_list(soup)

    return {
        "type_text": type_text,
        "address": address,
        "dispo": dispo,
        "area_m2": area_m2,
        "price_czk": price_czk,
        "price_per_m2": price_per_m2,
        "features": features,
    }

# ----------------- orchestrátor -----------------

def extract_new_listings(url: str, seen_ids: Set[str], scan_limit: int = 200, take: int = 10) -> Tuple[List[Dict[str, Any]], int]:
    """
    Stáhne search stránku, vytáhne detailové odkazy, a pro nové kusy
    doplní data z detailu (typ, adresa, m², cena, Kč/m², features).
    """
    work = normalize_search_url(url)
    html = fetch_page(work)
    items = extract_listing_links(html, base_url=work, max_links=scan_limit)

    new_items: List[Dict[str, Any]] = []
    for it in items:
        enriched = {**it}
        try:
            more = get_detail_fields(it["url"])
            enriched.update(more)
        except Exception:
            pass

        # fallback: pokud dispo / area / price chybí a jsou v title, zkus regex na title
        if enriched.get("dispo") is None:
            m = DISPO_RE.search(it["title"])
            if m:
                enriched["dispo"] = m.group(1).replace(" ", "")
        if enriched.get("area_m2") is None:
            m = AREA_RE.search(it["title"])
            if m:
                enriched["area_m2"] = _clean_float(m.group(1))
        if enriched.get("price_czk") is None:
            m = PRICE_RE.search(it["title"])
            if m:
                enriched["price_czk"] = _clean_int(m.group(1))
        if (
            enriched.get("price_per_m2") is None
            and enriched.get("price_czk")
            and enriched.get("area_m2")
        ):
            a = enriched["area_m2"]
            p = enriched["price_czk"]
            if isinstance(a, (int, float)) and a > 0 and isinstance(p, int):
                enriched["price_per_m2"] = round(p / a)

        # --- klíč pro "seen" = (id, cena) ---
        lid = it["id"]
        price = enriched.get("price_czk")
        key = f"{lid}:{price}" if price is not None else str(lid)

        if key in seen_ids:
            continue

        new_items.append(enriched)
        seen_ids.add(key)
        if len(new_items) >= take:
            break

    return new_items, len(items)