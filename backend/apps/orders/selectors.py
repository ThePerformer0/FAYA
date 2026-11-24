"""Requêtes de lecture des commandes strictement scopées (client vs responsable) sans N+1."""

from uuid import UUID

from django.db.models import Prefetch, QuerySet

from apps.accounts.models import User
from apps.core.exceptions import NotFoundDomainError
from apps.depots.models import Depot
from apps.orders.models import Order, OrderItem, OrderStatusHistory


def _hydrated_orders_qs() -> QuerySet[Order]:
    items_qs = OrderItem.objects.select_related(
        "product",
        "product__brand",
        "exchange_brand",
    ).order_by("created_at", "id")
    history_qs = OrderStatusHistory.objects.select_related("actor").order_by("created_at", "id")
    return Order.objects.select_related(
        "customer",
        "depot",
        "payment_record",
        "payment_record__recorded_by",
    ).prefetch_related(
        Prefetch("items", queryset=items_qs),
        Prefetch("status_history", queryset=history_qs),
    )


def list_customer_orders(
    *,
    customer: User,
    status: str | None = None,
) -> QuerySet[Order]:
    """Retourne les commandes appartenant strictement au client connecté."""
    qs = _hydrated_orders_qs().filter(customer=customer).order_by("-created_at", "-id")
    if status is not None:
        qs = qs.filter(status=status)
    return qs


def get_customer_order(*, customer: User, order_id: UUID) -> Order:
    """Retourne le détail d'une commande appartenant au client, sinon 404."""
    order = _hydrated_orders_qs().filter(pk=order_id, customer=customer).first()
    if order is None:
        raise NotFoundDomainError("Commande introuvable.", code="NOT_FOUND")
    return order


def list_depot_orders(
    *,
    depot: Depot,
    status: str | None = None,
) -> QuerySet[Order]:
    """Retourne les commandes appartenant strictement au dépôt du responsable connecté."""
    qs = _hydrated_orders_qs().filter(depot=depot).order_by("-created_at", "-id")
    if status is not None:
        qs = qs.filter(status=status)
    return qs


def get_depot_order(*, depot: Depot, order_id: UUID) -> Order:
    """Retourne le détail d'une commande appartenant au dépôt, sinon 404."""
    order = _hydrated_orders_qs().filter(pk=order_id, depot=depot).first()
    if order is None:
        raise NotFoundDomainError("Commande introuvable.", code="NOT_FOUND")
    return order
