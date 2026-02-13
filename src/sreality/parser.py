# sreality_watcher/sreality_parser.py
"""
HTML parser & data extractor for Sreality listings (no area-based filtering).

Provides:
- fetch_page(url) -> str
- extract_listing_links(html, base_url) -> list[dict]
- parse_title_fields(title) -> dict
- extract_new_listings(url, seen_ids, scan_limit=200, take=10) -> (list[dict], int)
  (nově každý záznam obsahuje i 'description')
"""

from __future__ import annotations
import re
import requests
from bs4 import BeautifulSoup  # pip install beautifulsoup4
from urllib.parse import urljoin, urlparse
from typing import Optional

# --------------------------
# Constants
# --------------------------
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; SrealityWatcher/modular)"
BASE_DOMAIN = "https://www.sreality.cz"
NBSP = u"\u00A0"

# Heuristiky pro tahání čísel z titulku
# Matches: "2 000 000 Kč", "1\u00A0500\u00A0000 Kč" or bare "2000000 Kč"
# Requires thousand-separator groups of exactly 3 digits so "Praha 5 2 000 000 Kč"
# correctly extracts 2 000 000 (not 52 000 000).
PRICE_RE = re.compile(
    r"(\d{1,3}(?:[\s" + NBSP + r"\u202F]\d{3})+|\d{4,})\s*Kč",
    re.IGNORECASE,
)
AREA_RE  = re.compile(r"(\d+(?:[.,]\d+)?)\s*m[²2]", re.IGNORECASE)
DISPO_RE = re.compile(r"\b(\d+\s*\+\s*(?:kk|1|2|3|4|5))\b", re.IGNORECASE)

# HEADERS pro scrapování detailu (tvůj stabilní setup)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "cs,en;q=0.9",
}


# --------------------------
# Field cleaning helpers
# --------------------------
def _clean_int(s: str):
    if not s:
        return None
    s = s.replace(NBSP, "").replace("\u200B", "").replace(" ", "").replace("\u202F", "").replace(",", "")
    try:
        return int(s)
    except Exception:
        return None


def _clean_float(s: str):
    if not s:
        return None
    s = s.replace(NBSP, "").replace(" ", "").replace("\u202F", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


# --------------------------
# Parse title fields
# --------------------------
def parse_title_fields(title: str) -> dict:
    """
    Z titulku (pokud to jde) vytáhne:
      - price_czk, area_m2, dispo, locality
    a spočítá:
      - price_per_m2
    Bez dalších filtrování/validací — jen best-effort parsování.
    """
    price = None
    m_price = PRICE_RE.search(title)
    if m_price:
        price = _clean_int(m_price.group(1))

    area = None
    m_area = AREA_RE.search(title)
    if m_area:
        area = _clean_float(m_area.group(1))

    dispo = None
    m_dispo = DISPO_RE.search(title)
    if m_dispo:
        dispo = m_dispo.group(1).replace(" ", "")

    locality = None
    if m_price:
        before_price = title[:m_price.start()].strip(" ,–-")
        if dispo:
            idx = before_price.lower().find(dispo.lower())
            if idx != -1:
                after = before_price[idx + len(dispo):].strip(" ,–-")
                m2pos = AREA_RE.search(after)
                locality = after[m2pos.end():].strip(" ,–-") if m2pos else after
        if not locality:
            parts = [p.strip() for p in before_price.split(",")]
            locality = ", ".join(parts[1:]) if len(parts) >= 2 else (before_price or None)

    price_per_m2 = None
    if price and area and area > 0:
        price_per_m2 = round(price / area)

    return {
        "price_czk": price,
        "area_m2": area,
        "dispo": dispo,
        "locality": locality,
        "price_per_m2": price_per_m2,
    }


# --------------------------
# Fetch HTML
# --------------------------
def fetch_page(url: str, timeout: int = 20, user_agent: str = DEFAULT_USER_AGENT) -> str:
    headers = {"User-Agent": user_agent}
    r = requests.get(url, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.text


# --------------------------
# URL helpers
# --------------------------
def _normalize_url(href: str, base_url: str) -> str:
    abs_url = urljoin(base_url, href.strip())
    parsed = urlparse(abs_url)
    abs_url = parsed._replace(fragment="").geturl()
    if "sreality.cz" not in abs_url:
        abs_url = urljoin(BASE_DOMAIN, abs_url)
    return abs_url


def _id_from_url(url_abs: str) -> str:
    """
    Extract numeric ID from the URL.
    e.g., /detail/prodej/byt/.../123456789 → 123456789
    """
    m = re.search(r"/(\d{6,})(?:$|[/?#])", url_abs)
    return m.group(1) if m else url_abs


# --------------------------
# Extract listing links
# --------------------------
def extract_listing_links(html: str, base_url: str, max_links: int = 200):
    """
    Vrátí list dictů: {id, url, title} pro všechny <a href="/detail/..."> (deduplikace dle id).
    Žádné filtrování podle m², ceny apod.
    """
    soup = BeautifulSoup(html, "lxml")
    anchors = soup.find_all("a", href=True)

    DETAIL_HREF_REGEX = re.compile(r"/detail/.*", re.IGNORECASE)

    results = []
    seen = set()

    for a in anchors:
        href = a["href"]
        if not DETAIL_HREF_REGEX.search(href):
            continue

        url_abs = _normalize_url(href, base_url)
        listing_id = _id_from_url(url_abs)

        if listing_id in seen:
            continue
        seen.add(listing_id)

        title = (
            a.get("aria-label")
            or a.get("title")
            or a.get_text(" ", strip=True)
            or url_abs
        ).strip() or url_abs

        results.append({"id": listing_id, "url": url_abs, "title": title})

        if len(results) >= max_links:
            break

    return results


# --------------------------
# Tvůj extraktor popisu
# --------------------------
def extract_description_from_text(text_block: str) -> str:
    """
    Vytáhne popis inzerátu z textového bloku.
    Heuristika:
    - ignoruje krátké / technické řádky
    - vezme první delší odstavec a vše následující,
      dokud nenarazí na hvězdičkový oddělovač nebo technické řádky.
    """
    lines = [ln.strip() for ln in text_block.splitlines()]

    def is_paragraph_start(l: str) -> bool:
        return len(l) > 30 and any(c.islower() for c in l)

    def is_noise_line(l: str) -> bool:
        """True for digit-only lines that come from price rendering artifacts."""
        stripped = l.replace(" ", "").replace(NBSP, "").replace("\u202F", "").replace(",", "").replace(".", "")
        return bool(stripped) and stripped.isdigit() and len(l) <= 15

    description_lines = []
    started = False

    for l in lines:
        if not l:
            continue

        # hvězdičkový oddělovač – často konec „lidského" textu
        if "* * *" in l and started:
            break

        # tvrdý stop pro technické informace (kdyby se do bloku dostaly)
        # "Cena" often appears as a standalone line (without colon) on Sreality
        _STOP = (
            "Cena", "Poznámka k ceně", "Příslušenství",
            "Energetická náročnost", "Stavba:", "Stav objektu:",
            "Podlaží:", "Plocha:", "Celková plocha", "Užitná plocha",
            "Lokalita:", "Vlastnictví:", "Ostatní:", "Zobrazeno:",
            "Vloženo:", "Upraveno:", "ID zakázky",
        )
        if l.startswith(_STOP) and started:
            break

        if not started:
            if is_paragraph_start(l):
                started = True
                description_lines.append(l)
        else:
            # skip digit-only noise lines (price rendered as individual spans)
            if is_noise_line(l):
                continue
            description_lines.append(l)

    return "\n".join(description_lines).strip()


def slice_between_markers(full_text: str) -> str:
    """
    Ořízne text stránky mezi 'Zpět' a 'Napsat prodejci' / 'Napsat makléři'.
    Když markery nenajde, vrátí původní text.
    """
    start_marker = "Zpět"
    end_markers = ["Napsat prodejci", "Napsat makléři"]

    start_idx = full_text.find(start_marker)
    if start_idx != -1:
        start_idx += len(start_marker)  # nechceme samotné slovo "Zpět"

    end_idx = -1
    for m in end_markers:
        pos = full_text.find(m)
        if pos != -1:
            if end_idx == -1 or pos < end_idx:
                end_idx = pos

    # když oba markery existují a pořadí dává smysl, ořízneme
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        return full_text[start_idx:end_idx].strip()

    # fallback – radši vrátíme celý text (a dál to zkusí heuristika)
    return full_text


def scrape_description(url: str) -> str:
    """Vrátí textový popis inzerátu ze Sreality detail stránky."""
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # 1) celá stránka jako text
    full_text = soup.get_text("\n", strip=True)

    # 2) oříznout na blok mezi 'Zpět' a 'Napsat ...'
    middle_block = slice_between_markers(full_text)

    # 3) z tohoto bloku vytáhnout samotný popis
    desc = extract_description_from_text(middle_block)
    if not desc:
        # fallback – zkusíme heuristiku na celý text, kdyby markery neseděly
        desc = extract_description_from_text(full_text)

    if not desc:
        raise ValueError("Nepodařilo se vytáhnout popis inzerátu.")

    return desc


def fetch_listing_description(url: str, timeout: int = 15) -> Optional[str]:
    """
    Wrapper nad extraktorem popisu.
    Vrací čistý text nebo None.
    """
    try:
        return scrape_description(url)
    except Exception:
        return None


# --------------------------
# Extract *new* listings
# --------------------------
def extract_new_listings(
    url: str,
    seen_ids: set,
    scan_limit: int = 200,
    take: int = 10,
):
    """
    Stáhne stránku → vytáhne odkazy → obohatí položky o parsed fields a popis.
    NEAPLIKUJE žádné další limity (m², cena, …).
    Vrací:
        new_items: list obohacených dictů (jen nové podle `seen_ids`)
        total_found: celkový počet nalezených na stránce
    Vedlejší efekt:
        `seen_ids` se doplňuje o ID nově vrácených položek.
    """
    html = fetch_page(url)
    listings = extract_listing_links(html, base_url=url, max_links=scan_limit)

    new_items = []
    for it in listings:
        lid = it["id"]

        # Nejprve z titulku vytáhneme cenu a další pole
        parsed = parse_title_fields(it["title"])
        price = parsed.get("price_czk")

        # Klíč pro "seen" = kombinace ID a ceny
        key = f"{lid}:{price}" if price is not None else str(lid)

        # Pokud už jsme tenhle (id, cena) viděli, přeskočíme
        if key in seen_ids:
            continue

        # obohacený záznam (id, url, title + parsed fields)
        enriched = {**it, **parsed}

        # doplnění popisu (může být None při failu)
        desc = fetch_listing_description(it["url"])
        enriched["description"] = desc

        # --- LOG DO TERMINÁLU ---
        print("=" * 80)
        print(f"[NEW LISTING] {lid} – {enriched.get('title', '')}")
        print(f"URL: {it['url']}")
        if desc:
            print("\n--- DESCRIPTION ---")
            print(desc)
        else:
            print("\n--- DESCRIPTION ---")
            print("(žádný popis se nepodařilo vytáhnout)")
        print("=" * 80)

        new_items.append(enriched)

        # za "seen" považujeme kombinaci ID a aktuální ceny
        seen_ids.add(key)

        if len(new_items) >= take:
            break

    return new_items, len(listings)