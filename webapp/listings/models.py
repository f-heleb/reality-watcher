from django.db import models


class SearchConfig(models.Model):
    """A Sreality search URL that the background scraper monitors."""

    name = models.CharField(max_length=200)
    url = models.URLField(max_length=2000)
    interval_sec = models.PositiveIntegerField(default=300)
    is_active = models.BooleanField(default=True)
    last_scraped = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Listing(models.Model):
    """One real estate listing scraped from Sreality."""

    listing_id = models.CharField(max_length=100, unique=True)
    url = models.URLField(max_length=2000)
    title = models.TextField()

    # Parsed structured fields
    price_czk = models.BigIntegerField(null=True, blank=True)
    area_m2 = models.FloatField(null=True, blank=True)
    dispo = models.CharField(max_length=50, blank=True)
    locality = models.CharField(max_length=300, blank=True)
    price_per_m2 = models.IntegerField(null=True, blank=True)

    # Full description text scraped from the detail page
    description = models.TextField(blank=True)

    # Image URLs scraped from the detail page
    images = models.JSONField(default=list, blank=True)

    # Contact info extracted from detail page {name, phone, agency}
    contact_info = models.JSONField(default=dict, blank=True)

    search_config = models.ForeignKey(
        SearchConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="listings",
    )
    first_seen = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-first_seen"]

    def __str__(self):
        return f"{self.dispo} {self.locality} – {self.price_czk} Kč"

    def to_dict(self):
        return {
            "id": self.pk,
            "listing_id": self.listing_id,
            "url": self.url,
            "title": self.title,
            "price_czk": self.price_czk,
            "area_m2": self.area_m2,
            "dispo": self.dispo,
            "locality": self.locality,
            "price_per_m2": self.price_per_m2,
            "description": self.description,
            "images": self.images or [],
            "contact_info": self.contact_info or {},
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "has_analysis": hasattr(self, "aianalysis"),
        }


class AIAnalysis(models.Model):
    """GPT-4 analysis for a listing, stored as JSON."""

    listing = models.OneToOneField(
        Listing, on_delete=models.CASCADE, related_name="aianalysis"
    )
    analysis_json = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Analysis for {self.listing}"
