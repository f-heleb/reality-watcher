"""
Scraper service: wraps src/sreality/parser.py and saves new listings to the DB.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _scrape_listing_detail(url: str) -> dict:
    """
    Fetch the detail page once, extract both images and contact info.
    Returns {"images": [...], "contact_info": {"name": ..., "phone": ..., "agency": ...}}.
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

        return {"images": images, "contact_info": contact}

    except Exception as exc:
        logger.debug("Detail scrape failed for %s: %s", url, exc)
        return {"images": [], "contact_info": {}}


def run_scrape(config) -> int:
    """
    Scrape the search URL in *config*, save any new listings to the DB,
    update config.last_scraped, and return the count of new listings saved.
    """
    from src.sreality.parser import extract_new_listings
    from src.sreality.watcher import Watcher
    from listings.models import Listing

    url = Watcher.normalize_search_url(config.url, force_first_page=True, cache_bust=True)

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
            detail = _scrape_listing_detail(listing_url) if listing_url else {}

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
                    "description": item.get("description", ""),
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
