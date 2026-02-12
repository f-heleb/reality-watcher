from django.contrib import admin
from listings.models import SearchConfig, Listing, AIAnalysis


@admin.register(SearchConfig)
class SearchConfigAdmin(admin.ModelAdmin):
    list_display = ["name", "url", "interval_sec", "is_active", "last_scraped"]
    list_editable = ["is_active", "interval_sec"]
    list_filter = ["is_active"]
    search_fields = ["name", "url"]


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ["listing_id", "dispo", "locality", "price_czk", "area_m2", "price_per_m2", "first_seen"]
    list_filter = ["dispo", "search_config"]
    search_fields = ["listing_id", "title", "locality", "description"]
    readonly_fields = ["listing_id", "first_seen"]
    date_hierarchy = "first_seen"


@admin.register(AIAnalysis)
class AIAnalysisAdmin(admin.ModelAdmin):
    list_display = ["listing", "created_at"]
    readonly_fields = ["listing", "analysis_json", "created_at"]
