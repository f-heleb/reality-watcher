import json
import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views import View
from django.views.generic import TemplateView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from listings.models import Listing, SearchConfig, AIAnalysis, OwnedProperty

logger = logging.getLogger(__name__)

class IndexView(LoginRequiredMixin, TemplateView):
    template_name = "listings/index.html"

class FilterOptionsView(LoginRequiredMixin, View):
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

class ListingListView(LoginRequiredMixin, View):
    PAGE_SIZE = 40

    def get(self, request):
        qs = Listing.objects.all()

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

class ListingDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        listing = get_object_or_404(Listing.objects.select_related("aianalysis"), pk=pk)
        data = listing.to_dict()
        # Include analysis if available
        try:
            data["analysis"] = listing.aianalysis.analysis_json
        except AIAnalysis.DoesNotExist:
            data["analysis"] = None
        return JsonResponse(data)


@method_decorator(csrf_exempt, name="dispatch")
class ListingAnalyzeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        listing = get_object_or_404(Listing, pk=pk)
        try:
            from listings.services.ai import analyze_listing

            analysis = analyze_listing(listing)
            return JsonResponse({"analysis": analysis})
        except Exception as exc:
            logger.exception("AI analysis failed for listing %d", pk)
            return JsonResponse({"error": str(exc)}, status=500)

@method_decorator(csrf_exempt, name="dispatch")
class SearchConfigListView(LoginRequiredMixin, View):
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
class SearchConfigDetailView(LoginRequiredMixin, View):
    def delete(self, request, pk):
        config = get_object_or_404(SearchConfig, pk=pk)
        try:
            from listings.scheduler import unschedule_config

            unschedule_config(config.pk)
        except Exception:
            pass
        config.delete()
        return JsonResponse({"deleted": pk})

@method_decorator(csrf_exempt, name="dispatch")
class SearchConfigScrapeNowView(LoginRequiredMixin, View):
    def post(self, request, pk):
        config = get_object_or_404(SearchConfig, pk=pk)
        try:
            from listings.services.scraper import run_scrape

            count = run_scrape(config)
            return JsonResponse({"new_listings": count})
        except Exception as exc:
            logger.exception("Manual scrape failed for config %d", pk)
            return JsonResponse({"error": str(exc)}, status=500)

class PropertiesView(LoginRequiredMixin, TemplateView):
    template_name = "listings/properties.html"


@method_decorator(csrf_exempt, name="dispatch")
class OwnedPropertyListView(LoginRequiredMixin, View):
    def get(self, request):
        props = OwnedProperty.objects.all()
        return JsonResponse({"results": [p.to_dict() for p in props]})

    def post(self, request):
        try:
            body = json.loads(request.body)
            prop = OwnedProperty.objects.create(
                name=body.get("name", "").strip() or "Bez názvu",
                address=body.get("address", "").strip(),
                description=body.get("description", "").strip(),
                dispo=body.get("dispo", "").strip(),
                area_m2=body.get("area_m2") or None,
                purchase_date=body.get("purchase_date") or None,
                purchase_price=body.get("purchase_price") or None,
                current_value=body.get("current_value") or None,
                total_invested=body.get("total_invested") or None,
                monthly_mortgage=body.get("monthly_mortgage") or None,
                monthly_fee=body.get("monthly_fee") or None,
                monthly_rent=body.get("monthly_rent") or None,
                notes=body.get("notes", "").strip(),
            )
            return JsonResponse(prop.to_dict(), status=201)
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class OwnedPropertyDetailView(LoginRequiredMixin, View):
    def get(self, request, pk):
        prop = get_object_or_404(OwnedProperty, pk=pk)
        return JsonResponse(prop.to_dict())

    def put(self, request, pk):
        prop = get_object_or_404(OwnedProperty, pk=pk)
        try:
            body = json.loads(request.body)
            for field in ["name", "address", "description", "notes", "dispo", "purchase_date"]:
                if field in body:
                    setattr(prop, field, body[field] or None if field == "purchase_date" else body[field])
            for field in ["purchase_price", "current_value", "total_invested",
                          "monthly_mortgage", "monthly_fee", "monthly_rent", "area_m2"]:
                if field in body:
                    setattr(prop, field, body[field] or None)
            prop.save()
            return JsonResponse(prop.to_dict())
        except Exception as exc:
            return JsonResponse({"error": str(exc)}, status=400)

    def delete(self, request, pk):
        prop = get_object_or_404(OwnedProperty, pk=pk)
        prop.delete()
        return JsonResponse({"deleted": pk})


class OwnedPropertyPriceEstimateView(LoginRequiredMixin, View):
    """
    GET /api/owned-properties/<pk>/estimate/
    Finds similar scraped listings by disposition family + area range + locality,
    computes median price/m², and estimates the current market value.

    Matching strategy (all filters applied simultaneously, locality broadened on fallback):
    - Disposition: any listing whose dispo starts with the same room number
      (e.g. "2+kk" and "2+1" both match owned property dispo "2+kk" or "2+1")
    - Area: within ±40% of prop.area_m2 (if set)
    - Locality: tries progressively broader keywords until results found
    """

    @staticmethod
    def _locality_candidates(address):
        """Return a list of locality keywords to try, broadest-first fallback."""
        if not address:
            return []
        parts = [p.strip() for p in address.split(",")]
        candidates = []
        # Last comma part, e.g. "Praha 2" from "Kodaňská 47, Praha 2"
        for part in reversed(parts):
            if any(c.isalpha() for c in part):
                candidates.append(part.strip())
                # First word only, e.g. "Praha"
                first_word = part.strip().split()[0]
                if first_word != part.strip():
                    candidates.append(first_word)
                break
        # Also try each remaining comma part (e.g. street name as fallback)
        for part in parts:
            kw = part.strip()
            if kw and kw not in candidates and any(c.isalpha() for c in kw):
                candidates.append(kw)
        return candidates

    def get(self, request, pk):
        import statistics
        import re

        prop = get_object_or_404(OwnedProperty, pk=pk)

        base_qs = Listing.objects.filter(price_per_m2__isnull=False, price_per_m2__gt=0)

        # ── Disposition filter (match same room-count family) ──────────────
        if prop.dispo:
            m = re.match(r"^(\d+)", prop.dispo.strip())
            if m:
                room_digit = m.group(1)
                # Match "2+kk", "2+1", "2+2", etc.
                base_qs = base_qs.filter(dispo__startswith=f"{room_digit}+")
            else:
                base_qs = base_qs.filter(dispo__iexact=prop.dispo)

        # ── Area filter (±40%) ─────────────────────────────────────────────
        if prop.area_m2:
            base_qs = base_qs.filter(
                area_m2__gte=prop.area_m2 * 0.60,
                area_m2__lte=prop.area_m2 * 1.40,
            )

        # ── Locality filter with progressive fallback ──────────────────────
        locality_used = ""
        locality_candidates = self._locality_candidates(prop.address)

        listings = []
        for kw in locality_candidates:
            qs = base_qs.filter(locality__icontains=kw).order_by("-first_seen")[:50]
            listings = list(qs)
            if listings:
                locality_used = kw
                break

        # Last fallback: no locality filter, just dispo + area
        if not listings:
            qs = base_qs.order_by("-first_seen")[:50]
            listings = list(qs)
            locality_used = ""

        if not listings:
            return JsonResponse(
                {"error": "Žádné podobné inzeráty nenalezeny.", "similar": [], "count": 0,
                 "locality_keyword": ""},
                status=200,
            )

        prices_m2 = [l.price_per_m2 for l in listings if l.price_per_m2]
        median_pm2 = int(statistics.median(prices_m2)) if prices_m2 else None

        estimated_value = None
        if median_pm2 and prop.area_m2:
            estimated_value = int(median_pm2 * prop.area_m2)

        # Sort by area proximity for the top-5 display
        if prop.area_m2:
            listings_sorted = sorted(
                listings, key=lambda l: abs((l.area_m2 or 0) - prop.area_m2)
            )
        else:
            listings_sorted = listings

        top5 = listings_sorted[:5]
        similar = [
            {
                "id": l.pk,
                "title": l.title,
                "dispo": l.dispo,
                "locality": l.locality,
                "price_czk": l.price_czk,
                "area_m2": l.area_m2,
                "price_per_m2": l.price_per_m2,
                "url": l.url,
                "first_seen": l.first_seen.isoformat() if l.first_seen else None,
            }
            for l in top5
        ]

        return JsonResponse(
            {
                "count": len(listings),
                "median_price_per_m2": median_pm2,
                "estimated_value": estimated_value,
                "locality_keyword": locality_used,
                "similar": similar,
            }
        )


@method_decorator(csrf_exempt, name="dispatch")
class OwnedPropertyPhotoUploadView(LoginRequiredMixin, View):
    def post(self, request, pk):
        import os
        from django.conf import settings as django_settings

        prop = get_object_or_404(OwnedProperty, pk=pk)
        uploaded = request.FILES.get("photo")
        if not uploaded:
            return JsonResponse({"error": "No file provided"}, status=400)

        ext = os.path.splitext(uploaded.name)[1].lower()
        if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
            return JsonResponse({"error": "Unsupported file type"}, status=400)

        prop_dir = django_settings.MEDIA_ROOT / "properties" / str(prop.pk)
        prop_dir.mkdir(parents=True, exist_ok=True)

        import uuid
        filename = f"{uuid.uuid4().hex}{ext}"
        filepath = prop_dir / filename

        with open(filepath, "wb") as f:
            for chunk in uploaded.chunks():
                f.write(chunk)

        url = f"{django_settings.MEDIA_URL}properties/{prop.pk}/{filename}"
        photos = list(prop.photos or [])
        photos.append(url)
        prop.photos = photos
        prop.save(update_fields=["photos"])
        return JsonResponse({"url": url, "photos": photos})
