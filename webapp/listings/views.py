import json
import logging

from django.db.models import Q, Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import TemplateView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from listings.models import Listing, SearchConfig, AIAnalysis

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------


class IndexView(TemplateView):
    template_name = "listings/index.html"


# ---------------------------------------------------------------------------
# Filter options (distinct dispo + locality values for sidebar)
# ---------------------------------------------------------------------------


class FilterOptionsView(View):
    def get(self, request):
        dispos = (
            Listing.objects.exclude(dispo="")
            .values_list("dispo", flat=True)
            .distinct()
            .order_by("dispo")
        )
        localities = (
            Listing.objects.exclude(locality="")
            .values_list("locality", flat=True)
            .distinct()
            .order_by("locality")
        )
        return JsonResponse(
            {
                "dispo": list(dispos),
                "locality": list(localities),
            }
        )


# ---------------------------------------------------------------------------
# Listing list (with filters + pagination)
# ---------------------------------------------------------------------------


class ListingListView(View):
    PAGE_SIZE = 40

    def get(self, request):
        qs = Listing.objects.all()

        # --- Filters ---
        config_id = request.GET.get("config_id")
        if config_id:
            qs = qs.filter(search_config_id=int(config_id))

        dispos = request.GET.getlist("dispo")
        if dispos:
            qs = qs.filter(dispo__in=dispos)

        localities = request.GET.getlist("locality")
        if localities:
            qs = qs.filter(locality__in=localities)

        price_min = request.GET.get("price_min")
        price_max = request.GET.get("price_max")
        if price_min:
            qs = qs.filter(price_czk__gte=int(price_min))
        if price_max:
            qs = qs.filter(price_czk__lte=int(price_max))

        area_min = request.GET.get("area_min")
        area_max = request.GET.get("area_max")
        if area_min:
            qs = qs.filter(area_m2__gte=float(area_min))
        if area_max:
            qs = qs.filter(area_m2__lte=float(area_max))

        search = request.GET.get("q")
        if search:
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(locality__icontains=search)
                | Q(description__icontains=search)
            )

        # --- Sort ---
        sort = request.GET.get("sort", "newest")
        sort_map = {
            "newest": "-first_seen",
            "oldest": "first_seen",
            "price_asc": "price_czk",
            "price_desc": "-price_czk",
            "area_asc": "area_m2",
            "area_desc": "-area_m2",
            "price_m2_asc": "price_per_m2",
            "price_m2_desc": "-price_per_m2",
        }
        qs = qs.order_by(sort_map.get(sort, "-first_seen"))

        # --- Pagination ---
        try:
            page = max(1, int(request.GET.get("page", 1)))
        except ValueError:
            page = 1
        offset = (page - 1) * self.PAGE_SIZE
        total = qs.count()
        items = qs.select_related("aianalysis")[offset : offset + self.PAGE_SIZE]

        return JsonResponse(
            {
                "total": total,
                "page": page,
                "page_size": self.PAGE_SIZE,
                "results": [l.to_dict() for l in items],
            }
        )


# ---------------------------------------------------------------------------
# Single listing detail
# ---------------------------------------------------------------------------


class ListingDetailView(View):
    def get(self, request, pk):
        listing = get_object_or_404(Listing.objects.select_related("aianalysis"), pk=pk)
        data = listing.to_dict()
        # Include analysis if available
        try:
            data["analysis"] = listing.aianalysis.analysis_json
        except AIAnalysis.DoesNotExist:
            data["analysis"] = None
        return JsonResponse(data)


# ---------------------------------------------------------------------------
# AI analysis (trigger on demand, cached after first call)
# ---------------------------------------------------------------------------


@method_decorator(csrf_exempt, name="dispatch")
class ListingAnalyzeView(View):
    def post(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        try:
            from listings.services.ai import analyze_listing

            analysis = analyze_listing(listing)
            return JsonResponse({"analysis": analysis})
        except Exception as exc:
            logger.exception("AI analysis failed for listing %d", pk)
            return JsonResponse({"error": str(exc)}, status=500)


# ---------------------------------------------------------------------------
# SearchConfig CRUD
# ---------------------------------------------------------------------------


@method_decorator(csrf_exempt, name="dispatch")
class SearchConfigListView(View):
    def get(self, request):
        configs = SearchConfig.objects.annotate(listing_count=Count("listings"))
        return JsonResponse(
            {
                "results": [
                    {
                        "id": c.pk,
                        "name": c.name,
                        "url": c.url,
                        "interval_sec": c.interval_sec,
                        "is_active": c.is_active,
                        "last_scraped": c.last_scraped.isoformat() if c.last_scraped else None,
                        "listing_count": c.listing_count,
                    }
                    for c in configs
                ]
            }
        )

    def post(self, request):
        try:
            body = json.loads(request.body)
            name = body.get("name", "").strip()
            url = body.get("url", "").strip()
            interval_sec = int(body.get("interval_sec", 300))
            if not name or not url:
                return JsonResponse({"error": "name and url are required"}, status=400)

            config = SearchConfig.objects.create(
                name=name,
                url=url,
                interval_sec=interval_sec,
                is_active=True,
            )

            # Schedule immediately
            try:
                from listings.scheduler import schedule_config

                schedule_config(config)
            except Exception as exc:
                logger.warning("Could not schedule config %d: %s", config.pk, exc)

            return JsonResponse({"id": config.pk, "name": config.name}, status=201)
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class SearchConfigDetailView(View):
    def delete(self, request, pk):
        config = get_object_or_404(SearchConfig, pk=pk)
        try:
            from listings.scheduler import unschedule_config

            unschedule_config(config.pk)
        except Exception:
            pass
        config.delete()
        return JsonResponse({"deleted": pk})


# ---------------------------------------------------------------------------
# Manual scrape trigger (for testing without waiting for the interval)
# ---------------------------------------------------------------------------


@method_decorator(csrf_exempt, name="dispatch")
class SearchConfigScrapeNowView(View):
    def post(self, request, pk):
        config = get_object_or_404(SearchConfig, pk=pk)
        try:
            from listings.services.scraper import run_scrape

            count = run_scrape(config)
            return JsonResponse({"new_listings": count})
        except Exception as exc:
            logger.exception("Manual scrape failed for config %d", pk)
            return JsonResponse({"error": str(exc)}, status=500)
