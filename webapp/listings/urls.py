from django.urls import path
from listings import views

urlpatterns = [
    # Main UI
    path("", views.IndexView.as_view(), name="index"),

    # Listings API
    path("api/listings/", views.ListingListView.as_view(), name="listing-list"),
    path("api/listings/<int:pk>/", views.ListingDetailView.as_view(), name="listing-detail"),
    path("api/listings/<int:pk>/analyze/", views.ListingAnalyzeView.as_view(), name="listing-analyze"),

    # Filter options
    path("api/filter-options/", views.FilterOptionsView.as_view(), name="filter-options"),

    # Search configs
    path("api/search-configs/", views.SearchConfigListView.as_view(), name="search-config-list"),
    path("api/search-configs/<int:pk>/", views.SearchConfigDetailView.as_view(), name="search-config-detail"),
    path("api/search-configs/<int:pk>/scrape-now/", views.SearchConfigScrapeNowView.as_view(), name="search-config-scrape-now"),
]
