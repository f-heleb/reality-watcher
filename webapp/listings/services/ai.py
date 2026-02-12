"""
AI service: wraps src/core/ai_analysis.py and persists the result to AIAnalysis.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def analyze_listing(listing) -> dict:
    """
    Run GPT analysis for *listing*.  If an AIAnalysis row already exists,
    return the cached result.  Otherwise call the API, persist, and return.
    """
    from src.core.ai_analysis import call_chatgpt_for_listing
    from listings.models import AIAnalysis

    # Return cached analysis if available
    try:
        existing = AIAnalysis.objects.get(listing=listing)
        return existing.analysis_json
    except AIAnalysis.DoesNotExist:
        pass

    # Build the listing dict that ai_analysis.py expects
    listing_data = {
        "title": listing.title,
        "url": listing.url,
        "locality": listing.locality,
        "location": listing.locality,
        "price_czk": listing.price_czk,
        "area_m2": listing.area_m2,
        "dispo": listing.dispo,
        "price_per_m2": listing.price_per_m2,
        "description": listing.description,
    }

    analysis = call_chatgpt_for_listing(listing_data)

    AIAnalysis.objects.update_or_create(
        listing=listing,
        defaults={"analysis_json": analysis},
    )

    return analysis
