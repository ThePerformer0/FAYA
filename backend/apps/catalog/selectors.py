"""Requêtes de lecture du catalogue central (uniquement éléments actifs et publiés)."""

from decimal import Decimal
from uuid import UUID

from django.db.models import QuerySet

from apps.catalog.models import Brand, Product, ProductStatus


def list_active_brands() -> QuerySet[Brand]:
    """Retourne les marques actives du catalogue central."""
    return Brand.objects.filter(is_active=True).order_by("name")


def list_published_products(
    *,
    brand_id: UUID | None = None,
    capacity_kg: Decimal | None = None,
    product_type: str | None = None,
) -> QuerySet[Product]:
    """Retourne uniquement les produits publiés de marques actives."""
    qs = (
        Product.objects.select_related("brand")
        .filter(status=ProductStatus.PUBLISHED, brand__is_active=True)
        .order_by("brand__name", "capacity_kg", "name")
    )
    if brand_id is not None:
        qs = qs.filter(brand_id=brand_id)
    if capacity_kg is not None:
        qs = qs.filter(capacity_kg=capacity_kg)
    if product_type:
        qs = qs.filter(product_type=product_type)
    return qs
