"""
Scraper service: wraps src/sreality/parser.py and saves new listings to the DB.
"""
from __future__ import annotations

import logging
import re
import requests
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def normalize_search_url(u: str, force_first_page: bool = True, cache_bust: bool = False) -> str:
    """Normalize and optionally cache-bust a Sreality search URL."""
    if not u:
        return u
    url = str(u)
    if force_first_page:
        # Remove page=... query params commonly used by Sreality
        url = re.sub(r"([?&])page=\d+", "", url)
    if cache_bust:
        # append a short timestamp param to avoid cached results
        sep = "&" if "?" in url else "?"
        import time
        url = f"{url}{sep}_cb={int(time.time())}"
    return url


def extract_new_listings(search_url: str, seen_ids: set, scan_limit: int = 300, take: int = 50):
    """A lightweight extractor for Sreality search pages.
    
    Returns (new_items, total_found). Each item is a dict with keys:
    - id, url, title, price_czk, area_m2, dispo, locality, description
    """
    try:
        resp = requests.get(search_url, timeout=15, headers={
            "User-Agent": "Mozilla/5.0 (compatible)"
        })
        resp.raise_for_status()
    except Exception:
        raise

    soup = BeautifulSoup(resp.text, "lxml")

    # Extract all listing detail links
    anchors = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/detail/" in href:
            full = href if href.startswith("http") else urljoin(search_url, href)
            anchors.append((full, (a.get_text(" ") or "").strip()))

    # Deduplicate preserving order
    seen_set = set()
    unique = []
    for url, text in anchors:
        if url in seen_set:
            continue
        seen_set.add(url)
        unique.append((url, text))

    total = len(unique)

    items = []
    for url, text in unique[:scan_limit]:
        # Derive an id from the URL (last path segment)
        try:
            path = urlparse(url).path.rstrip("/")
            lid = path.split("/")[-1] or url
        except Exception:
            lid = url

        if lid in seen_ids:
            continue

        # Parse text to extract structured fields
        # Text typically looks like: "2+kk, 45 m², 3 500 000 Kč, Praha 2"
        price = None
        area = None
        dispo = ""
        locality = ""

        # Clean up the text for parsing
        clean_text = text.strip()
        parts = [p.strip() for p in clean_text.split(",")]

        # Try to identify fields by pattern matching
        for part in parts:
            part = part.strip()
            
            # Check if it's a disposition (2+kk, 1+1, etc.)
            if re.match(r"^\d+\+[a-z0-9]+$", part, re.IGNORECASE):
                dispo = part
                continue
            
            # Check if it's a price (e.g., "3 500 000 Kč" or "5000000 Kč")
            m = re.search(r"(\d[\d\s]*\d)\s*Kč", part)
            if m and not price:
                try:
                    price = int(re.sub(r"[\s]", "", m.group(1)))
                except Exception:
                    pass
                continue

            # Check if it's an area (e.g., "45 m²" or "45 m2")
            m2 = re.search(r"(\d+[\.,]?\d*)\s*m(?:\u00B2|2)", part)
            if m2 and not area:
                try:
                    area = float(m2.group(1).replace(",", "."))
                except Exception:
                    pass
                continue

            # If it doesn't match above patterns and we haven't found locality, use it
            if not locality and len(part) > 2:
                # Check if it looks like a location (contains city name patterns)
                if any(city in part for city in [
                    "Praha", "Brno", "Ostrava", "Plzeň", "Liberec",
                    "Olomouc", "Ceské Budějovice", "Hradec Králové", "Pardubice",
                    "Praha", "Zlin", "Jihlava",
                ]) or not any(c in part for c in ["Kč", "m²", "m2"]):
                    locality = part

        # If locality is empty, try to extract from URL or use "Česká Republika"
        if not locality:
            # Try extracting from URL query params (if present)
            from urllib.parse import parse_qs, urlparse as u_parse
            parsed = u_parse(url)
            if "region" in parsed.path.lower() or "location" in parsed.path.lower():
                locality = "Praha"  # Default fallback
            else:
                locality = ""

        items.append({
            "id": lid,
            "url": url,
            "title": clean_text,  # Use the full text as title
            "price_czk": price,
            "area_m2": area,
            "dispo": dispo,
            "locality": locality,
            "description": "",  # Will be fetched from detail page
        })

        if len(items) >= take:
            break

    return items, total


def _scrape_listing_detail(url: str) -> dict:
    """
    Fetch the detail page once, extract images, contact info, and description.
    Returns {"images": [...], "contact_info": {...}, "description": "..."}.
    """
    try:
        import json
        import re
        import requests
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/129.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "cs,en;q=0.9",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # ── Images ────────────────────────────────────────────────────────
        images: list[str] = []
        seen: set[str] = set()

        og = soup.find("meta", attrs={"property": "og:image"})
        if og and og.get("content"):
            src = og["content"].strip()
            if src and src not in seen:
                images.append(src)
                seen.add(src)

        for img in soup.find_all("img"):
            src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-lazy-src")
                or ""
            )
            if not src:
                srcset = img.get("srcset", "")
                if srcset:
                    src = srcset.split(",")[0].strip().split(" ")[0]
            if not src or src.startswith("data:"):
                continue
            if not src.startswith("http"):
                src = urljoin(url, src)
            low = src.lower()
            if any(x in low for x in ["icon", "logo", "favicon", "placeholder", "spinner", "avatar"]):
                continue
            if not any(ext in low for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                continue
            if src not in seen:
                images.append(src)
                seen.add(src)
            if len(images) >= 15:
                break

        # ── Contact info ──────────────────────────────────────────────────
        contact: dict = {}

        # 1) Try JSON-LD structured data (Person / RealEstateAgent / Organization)
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                entries = data if isinstance(data, list) else [data]
                for entry in entries:
                    t = entry.get("@type", "")
                    if any(x in t for x in ("Person", "Agent", "Organization", "RealEstate")):
                        if not contact.get("name"):
                            contact["name"] = entry.get("name", "")
                        if not contact.get("phone"):
                            contact["phone"] = entry.get("telephone", "")
                        if not contact.get("agency"):
                            org = entry.get("worksFor") or entry.get("memberOf") or {}
                            contact["agency"] = org.get("name", "") if isinstance(org, dict) else ""
            except Exception:
                pass

        # 2) Fallback: look for phone numbers in the full page text
        if not contact.get("phone"):
            full_text = soup.get_text(" ", strip=True)
            phone_match = re.search(
                r"(\+420[\s\-]?\d{3}[\s\-]?\d{3}[\s\-]?\d{3}|\b\d{3}[\s\-]\d{3}[\s\-]\d{3}\b)",
                full_text,
            )
            if phone_match:
                contact["phone"] = re.sub(r"[\s\-]+", " ", phone_match.group(1)).strip()

        # 3) Fallback: meta author / og:site_name
        if not contact.get("name"):
            author = soup.find("meta", attrs={"name": "author"})
            if author and author.get("content"):
                contact["name"] = author["content"].strip()

        # Remove empty keys
        contact = {k: v for k, v in contact.items() if v}

        # ── Description ───────────────────────────────────────────────────
        # Try to extract main property description from common containers
        description = ""
        
        # Common Sreality selectors for description
        desc_selectors = [
            ".property-description",
            ".description",
            "[data-testid='description']",
            ".text-description",
            ".text-info",
            "article",
            "main",
        ]
        
        for selector in desc_selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(" ", strip=True)
                if len(text) > 50:  # Only use if it's substantial
                    description = text[:2000]  # Limit to 2000 chars
                    break
        
        # If no description found, try extracting from all divs with substantial text
        if not description:
            for div in soup.find_all(["div", "section"]):
                text = div.get_text(" ", strip=True)
                if 200 < len(text) < 5000:  # Look for medium-sized content blocks
                    # Skip navigation/footer areas
                    if not any(x in text.lower() for x in ["navigace", "footer", "menu", "cookie"]):
                        description = text[:2000]
                        break

        return {
            "images": images,
            "contact_info": contact,
            "description": description,
        }

    except Exception as exc:
        logger.debug("Detail scrape failed for %s: %s", url, exc)
        return {"images": [], "contact_info": {}, "description": ""}


def run_scrape(config) -> int:
    """
    Scrape the search URL in *config*, save any new listings to the DB,
    update config.last_scraped, and return the count of new listings saved.
    """
    from listings.models import Listing

    # Normalize URL (force first page, cache-bust to avoid stale results)
    url = normalize_search_url(config.url, force_first_page=True, cache_bust=True)

    # Build set of already-seen listing IDs for this config
    seen_ids: set[str] = set(
        Listing.objects.filter(search_config=config).values_list("listing_id", flat=True)
    )

    try:
        new_items, _total = extract_new_listings(
            url,
            seen_ids,
            scan_limit=300,
            take=50,
        )
    except Exception as exc:
        logger.error("Scrape failed for config %s: %s", config.name, exc)
        return 0

    saved = 0
    for item in new_items:
        try:
            listing_url = item.get("url", "")
            # Fetch detail page to get images, contact info, and full description
            detail = _scrape_listing_detail(listing_url) if listing_url else {}
            
            # Merge detail data into item
            description = detail.get("description", "") or item.get("description", "")
            
            Listing.objects.get_or_create(
                listing_id=item["id"],
                defaults={
                    "url": listing_url,
                    "title": item.get("title", ""),
                    "price_czk": item.get("price_czk"),
                    "area_m2": item.get("area_m2"),
                    "dispo": item.get("dispo", ""),
                    "locality": item.get("locality", ""),
                    "price_per_m2": item.get("price_per_m2"),
                    "description": description,  # Use full description from detail page
                    "images": detail.get("images", []),
                    "contact_info": detail.get("contact_info", {}),
                    "search_config": config,
                },
            )
            saved += 1
        except Exception as exc:
            logger.error("Failed to save listing %s: %s", item.get("id"), exc)

    config.last_scraped = datetime.now(tz=timezone.utc)
    config.save(update_fields=["last_scraped"])

    if saved:
        logger.info("Config '%s': saved %d new listings.", config.name, saved)

    return saved
