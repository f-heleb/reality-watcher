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

    @property
    def offer_type(self):
        if "prodej" in self.url:
            return "prodej"
        if "pronajem" in self.url:
            return "pronájem"
        return ""

    @property
    def object_type(self):
        import re
        m = re.search(r"\b(Byt|Dům|Pozemek|Garáž|Komerční|Chata)\b", self.title, re.IGNORECASE)
        if m:
            return m.group(1)
        return "Byt"

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
            "offer_type": self.offer_type,
            "object_type": self.object_type,
            "price_per_m2": self.price_per_m2,
            "description": self.description,
            "images": self.images or [],
            "contact_info": self.contact_info or {},
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "has_analysis": hasattr(self, "aianalysis"),
        }


class OwnedProperty(models.Model):
    """A property owned by the user — for personal portfolio tracking."""

    name = models.CharField(max_length=200)
    address = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    photos = models.JSONField(default=list, blank=True)

    # Property details (used for price estimation)
    dispo = models.CharField(max_length=50, blank=True)   # e.g. "2+kk"
    area_m2 = models.FloatField(null=True, blank=True)    # floor area

    # Financials
    purchase_price = models.BigIntegerField(null=True, blank=True)   # pořizovací cena
    current_value = models.BigIntegerField(null=True, blank=True)    # odhadovaná hodnota
    total_invested = models.BigIntegerField(null=True, blank=True)   # celkem vloženo (koupě + rekonstrukce)
    monthly_mortgage = models.IntegerField(null=True, blank=True)    # splátka hypotéky
    monthly_fee = models.IntegerField(null=True, blank=True)         # fond oprav / správa
    monthly_rent = models.IntegerField(null=True, blank=True)        # příjem z pronájmu

    purchase_date = models.DateField(null=True, blank=True)   # datum koupě

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def roi(self):
        base = self.total_invested or self.purchase_price
        if base and base > 0 and self.current_value:
            return round((self.current_value - base) / base * 100, 1)
        return None

    @property
    def years_held(self):
        if not self.purchase_date:
            return None
        from datetime import date
        return round((date.today() - self.purchase_date).days / 365.25, 1)

    @property
    def roi_annual(self):
        """CAGR — compound annual growth rate since purchase_date."""
        years = self.years_held
        if not years or years < 0.1:
            return None
        base = self.total_invested or self.purchase_price
        if not base or base <= 0 or not self.current_value:
            return None
        return round(((self.current_value / base) ** (1 / years) - 1) * 100, 1)

    @property
    def cashflow(self):
        income = self.monthly_rent or 0
        costs = (self.monthly_mortgage or 0) + (self.monthly_fee or 0)
        if income or costs:
            return income - costs
        return None

    def to_dict(self):
        return {
            "id": self.pk,
            "name": self.name,
            "address": self.address,
            "description": self.description,
            "photos": self.photos or [],
            "dispo": self.dispo,
            "area_m2": self.area_m2,
            "purchase_price": self.purchase_price,
            "current_value": self.current_value,
            "total_invested": self.total_invested,
            "monthly_mortgage": self.monthly_mortgage,
            "monthly_fee": self.monthly_fee,
            "monthly_rent": self.monthly_rent,
            "purchase_date": self.purchase_date.isoformat() if self.purchase_date else None,
            "notes": self.notes,
            "roi": self.roi,
            "roi_annual": self.roi_annual,
            "years_held": self.years_held,
            "cashflow": self.cashflow,
            "created_at": self.created_at.isoformat() if self.created_at else None,
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
