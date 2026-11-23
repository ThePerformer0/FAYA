"""Requêtes de lecture géospatiales et calcul d'ouverture des dépôts (CDC §2.2, §9)."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.db.models import (
    Case,
    Exists,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Value,
    When,
)
from django.utils import timezone

from apps.catalog.models import ProductStatus
from apps.core.exceptions import NotFoundDomainError
from apps.core.models import PlatformSetting
from apps.depots.models import (
    Depot,
    DepotProductOffer,
    DepotStatus,
    OfferExchangeBrand,
    OfferOperation,
)


class OpenStatus:
    OPEN = "OPEN"
    CLOSING_SOON = "CLOSING_SOON"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class DepotOpenState:
    open_status: str
    can_order: bool
    last_order_time: time
    reopens_at: time


def compute_depot_open_state(
    *,
    depot: Depot,
    settings_obj: PlatformSetting | None = None,
    at: datetime | None = None,
) -> DepotOpenState:
    """Calcule l'état d'ouverture et la possibilité de commander dans le fuseau plateforme."""
    cfg = settings_obj or PlatformSetting.load()
    tz = ZoneInfo(cfg.timezone)
    local_now = (at or timezone.now()).astimezone(tz)

    opening_dt = datetime.combine(local_now.date(), depot.opening_time, tzinfo=tz)
    closing_dt = datetime.combine(local_now.date(), depot.closing_time, tzinfo=tz)
    cutoff_dt = closing_dt - timedelta(minutes=cfg.order_cutoff_before_close_minutes)
    closing_soon_dt = closing_dt - timedelta(minutes=cfg.closing_soon_threshold_minutes)

    last_order_time = max(opening_dt, cutoff_dt).time()

    if local_now < opening_dt or local_now >= closing_dt:
        return DepotOpenState(
            open_status=OpenStatus.CLOSED,
            can_order=False,
            last_order_time=last_order_time,
            reopens_at=depot.opening_time,
        )

    can_order = local_now < cutoff_dt
    is_closing_soon = local_now >= closing_soon_dt or not can_order
    return DepotOpenState(
        open_status=OpenStatus.CLOSING_SOON if is_closing_soon else OpenStatus.OPEN,
        can_order=can_order,
        last_order_time=last_order_time,
        reopens_at=depot.opening_time,
    )


def _public_offers_prefetch() -> Prefetch:
    active_ops = OfferOperation.objects.filter(is_active=True).order_by("operation_type")
    exchange_brands = (
        OfferExchangeBrand.objects.select_related("accepted_brand")
        .filter(accepted_brand__is_active=True)
        .order_by("accepted_brand__name")
    )
    offers_qs = (
        DepotProductOffer.objects.select_related("product", "product__brand")
        .filter(
            is_active=True,
            product__status=ProductStatus.PUBLISHED,
            product__brand__is_active=True,
        )
        .prefetch_related(
            Prefetch("operations", queryset=active_ops, to_attr="active_operations"),
            Prefetch("exchange_brands", queryset=exchange_brands, to_attr="active_exchange_brands"),
        )
        .order_by("product__brand__name", "product__capacity_kg")
    )
    return Prefetch("offers", queryset=offers_qs, to_attr="public_offers")


def search_public_depots(
    *,
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float | None = None,
    q: str | None = None,
    brand_id: UUID | None = None,
    capacity_kg: Decimal | None = None,
    operation_type: str | None = None,
    open_now: bool = False,
    settings_obj: PlatformSetting | None = None,
    at: datetime | None = None,
) -> QuerySet[Depot]:
    """Recherche les dépôts actifs, triés ouverts d'abord puis par distance PostGIS."""
    cfg = settings_obj or PlatformSetting.load()
    tz = ZoneInfo(cfg.timezone)
    local_time = (at or timezone.now()).astimezone(tz).time()

    qs = Depot.objects.filter(status=DepotStatus.ACTIVE).prefetch_related(_public_offers_prefetch())

    if q and q.strip():
        term = q.strip()
        qs = qs.filter(
            Q(name__icontains=term)
            | Q(address__icontains=term)
            | Q(neighborhood__icontains=term)
        )

    if brand_id is not None or capacity_kg is not None or operation_type is not None:
        offer_subquery = DepotProductOffer.objects.filter(
            depot_id=OuterRef("pk"),
            is_active=True,
            product__status=ProductStatus.PUBLISHED,
            product__brand__is_active=True,
        )
        if brand_id is not None:
            offer_subquery = offer_subquery.filter(product__brand_id=brand_id)
        if capacity_kg is not None:
            offer_subquery = offer_subquery.filter(product__capacity_kg=capacity_kg)
        if operation_type is not None:
            offer_subquery = offer_subquery.filter(
                operations__operation_type=operation_type,
                operations__is_active=True,
            )
        qs = qs.filter(Exists(offer_subquery))

    if open_now:
        qs = qs.filter(opening_time__lte=local_time, closing_time__gt=local_time)

    # Ouverts (OPEN / CLOSING_SOON) avant les fermés (DESIGN_SYSTEM §3.5)
    qs = qs.annotate(
        is_closed_rank=Case(
            When(opening_time__lte=local_time, closing_time__gt=local_time, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    )

    if lat is not None and lng is not None:
        user_point = Point(float(lng), float(lat), srid=4326)
        if radius_km is not None:
            qs = qs.filter(location__distance_lte=(user_point, D(km=radius_km)))
        qs = qs.annotate(distance_geo=Distance("location", user_point)).order_by(
            "is_closed_rank", "distance_geo", "name"
        )
    else:
        qs = qs.order_by("is_closed_rank", "name")

    return qs


def get_public_depot_detail(*, depot_id: UUID) -> Depot:
    """Retourne un dépôt actif avec ses offres publiées, sinon 404."""
    depot = (
        Depot.objects.filter(pk=depot_id, status=DepotStatus.ACTIVE)
        .prefetch_related(_public_offers_prefetch())
        .first()
    )
    if depot is None:
        raise NotFoundDomainError("Dépôt introuvable.", code="NOT_FOUND")
    return depot
