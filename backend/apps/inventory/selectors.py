"""Requêtes de lecture des stocks et mouvements strictement scopées par dépôt."""

from uuid import UUID

from django.db.models import QuerySet

from apps.depots.models import Depot
from apps.inventory.models import DepotStock, StockMovement


def list_depot_stocks(
    *,
    depot: Depot,
    product_id: UUID | None = None,
    category: str | None = None,
) -> QuerySet[DepotStock]:
    """Liste les lignes de stock appartenant exclusivement au dépôt donné."""
    qs = (
        DepotStock.objects.select_related("product", "product__brand")
        .filter(depot=depot)
        .order_by("product__brand__name", "product__capacity_kg", "product__name", "category", "id")
    )
    if product_id is not None:
        qs = qs.filter(product_id=product_id)
    if category is not None:
        qs = qs.filter(category=category)
    return qs


def list_depot_stock_movements(
    *,
    depot: Depot,
    product_id: UUID | None = None,
    category: str | None = None,
    movement_type: str | None = None,
) -> QuerySet[StockMovement]:
    """Liste l'historique immuable des mouvements appartenant exclusivement au dépôt donné."""
    qs = (
        StockMovement.objects.select_related("product", "product__brand", "actor")
        .filter(depot=depot)
        .order_by("-created_at", "-id")
    )
    if product_id is not None:
        qs = qs.filter(product_id=product_id)
    if category is not None:
        qs = qs.filter(category=category)
    if movement_type is not None:
        qs = qs.filter(movement_type=movement_type)
    return qs
