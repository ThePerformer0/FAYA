"""Fabriques et helpers partagés du Jalon 3 (module ``orders``).

Boîte noire stricte : seules les signatures publiques fournies dans le contrat
sont utilisées. Les rares endroits où un nom de champ n'est pas garanti par le
contrat (``CustomerSuspension``, champ « type » de ``StockMovement``) passent par
une introspection du modèle afin de ne pas figer d'hypothèse fragile.

Horloge : tout est exprimé en ``Africa/Douala`` (UTC+1). Les dépôts créés par
``make_depot()`` ouvrent de 08:00 à 20:00. ``BASE_NOW`` (10:00) est donc
toujours « ouvert » et hors fenêtre de coupure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apps.accounts.models import CustomerSuspension, SuspensionReason, UserRole
from apps.depots.models import DepotStatus, OperationType
from apps.inventory.models import (
    DepotStock,
    StockCategory,
    StockMovement,
    StockReservation,
)
from apps.orders import services as order_services
from apps.orders.models import Order, OrderStatus, OrderStatusHistory, PaymentMethod

try:  # ``ProductStatus`` vit dans le catalogue ; repli sur la fabrique qui l'importe.
    from apps.catalog.models import ProductStatus
except ImportError:  # pragma: no cover
    from tests.factories_catalog import ProductStatus

from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import (
    make_depot,
    make_depot_manager,
    make_exchange_brand,
    make_offer,
    make_operation,
)
from tests.factories_inventory import make_stock
from tests.helpers import create_user

# --------------------------------------------------------------------------- #
# Horloge
# --------------------------------------------------------------------------- #
DOUALA = ZoneInfo("Africa/Douala")
BASE_NOW = datetime(2026, 3, 4, 10, 0, tzinfo=DOUALA)
FROZEN_ISO = "2026-03-04 10:00:00+01:00"  # pour freezegun, == BASE_NOW

NON_PUBLISHED_STATUS = next(s for s in ProductStatus if s != ProductStatus.PUBLISHED)
NONEXISTENT_ID = "00000000-0000-0000-0000-000000000000"

AUTO = object()  # sentinelle : « choisis la marque d'échange par défaut »


def at(hour: int, minute: int = 0, second: int = 0, *, day: int = 4) -> datetime:
    """Datetime aware ``Africa/Douala`` le ``day`` mars 2026."""
    return datetime(2026, 3, day, hour, minute, second, tzinfo=DOUALA)


# --------------------------------------------------------------------------- #
# Clés exactes des serializers (contrat Lot 4)
# --------------------------------------------------------------------------- #
CUSTOMER_ORDER_KEYS = frozenset(
    {
        "id", "reference", "depot", "status", "payment_status", "total_amount",
        "response_deadline_at", "pickup_deadline_at", "confirmed_at", "picked_up_at",
        "refused_at", "cancelled_at", "expired_at", "status_reason",
        "cancellation_source", "counted_as_no_show", "items", "payment",
        "status_history", "created_at", "updated_at",
    }
)
ORDER_ITEM_KEYS = frozenset(
    {
        "id", "product_id", "brand_name", "product_name", "capacity_kg",
        "operation_type", "exchange_brand_name", "quantity", "unit_gas_price",
        "unit_bottle_price", "unit_deposit_amount", "unit_total_price",
        "line_total_amount",
    }
)
PAYMENT_KEYS = frozenset(
    {
        "id", "expected_amount", "received_amount", "payment_method", "status",
        "external_reference", "notes", "paid_at",
    }
)
DEPOT_ORDER_KEYS = CUSTOMER_ORDER_KEYS | {"customer"}
DEPOT_CUSTOMER_KEYS = frozenset({"full_name", "phone"})
FORBIDDEN_PRIVACY_KEYS = frozenset({"email", "password", "customer_id", "user_id"})


def walk_keys(data: Any):
    """Itère récursivement sur toutes les clés d'une structure JSON."""
    if isinstance(data, dict):
        for key, value in data.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(data, list):
        for value in data:
            yield from walk_keys(value)


def error_code(exc: BaseException) -> str | None:
    return getattr(exc, "code", None)


# --------------------------------------------------------------------------- #
# Mise en place catalogue / dépôt / stock
# --------------------------------------------------------------------------- #
@dataclass
class OrderSetup:
    manager: Any
    depot: Any
    product: Any
    offer: Any
    operations: dict = field(default_factory=dict)  # OperationType -> OfferOperation
    stock: Any = None  # DepotStock FULL du produit
    new_stock: Any = None  # DepotStock NEW du produit (optionnel)
    exchange_brand: Any = None  # marque acceptée en échange (Brand)
    exchange_link: Any = None  # OfferExchangeBrand
    exchange_product: Any = None  # produit de la marque d'échange, même capacité


def make_order_setup(
    *,
    manager=None,
    depot_status=DepotStatus.ACTIVE,
    physical: int = 10,
    reserved: int = 0,
    new_physical: int | None = None,
    operations=(OperationType.REFILL, OperationType.EXCHANGE, OperationType.FIRST_ACQUISITION),
    gas_price: int = 1000,
    exchange_gas_price: int = 1500,
    first_bottle_price: int = 5000,
    first_deposit_amount: int = 2000,
    product=None,
) -> OrderSetup:
    """Dépôt ACTIVE + produit publié + offre + opérations + stock FULL.

    Prix par défaut : REFILL 1000 ; EXCHANGE 1500 ; FIRST_ACQUISITION 1000 + 5000
    (bouteille) + 2000 (consigne) = 8000 par unité.
    """
    manager = manager or make_depot_manager()
    depot = make_depot(manager=manager, status=depot_status)
    product = product or make_product()
    offer = make_offer(depot, product)

    ops: dict = {}
    if OperationType.REFILL in operations:
        ops[OperationType.REFILL] = make_operation(
            offer, OperationType.REFILL, gas_price=gas_price
        )
    exchange_brand = exchange_link = exchange_product = None
    if OperationType.EXCHANGE in operations:
        ops[OperationType.EXCHANGE] = make_operation(
            offer, OperationType.EXCHANGE, gas_price=exchange_gas_price
        )
        exchange_brand = make_brand()  # JAMAIS de name fixe (unicité insensible à la casse)
        exchange_link = make_exchange_brand(offer, accepted_brand=exchange_brand)
        exchange_product = make_product(
            brand=exchange_brand,
            capacity_kg=product.capacity_kg,
            product_type=product.product_type,
        )
    if OperationType.FIRST_ACQUISITION in operations:
        ops[OperationType.FIRST_ACQUISITION] = make_operation(
            offer,
            OperationType.FIRST_ACQUISITION,
            gas_price=gas_price,
            bottle_price=first_bottle_price,
            deposit_amount=first_deposit_amount,
        )

    stock = make_stock(
        depot=depot,
        product=product,
        category=StockCategory.FULL,
        physical_quantity=physical,
        reserved_quantity=reserved,
    )
    new_stock = None
    if new_physical is not None:
        new_stock = make_stock(
            depot=depot,
            product=product,
            category=StockCategory.NEW,
            physical_quantity=new_physical,
        )
    return OrderSetup(
        manager=manager,
        depot=depot,
        product=product,
        offer=offer,
        operations=ops,
        stock=stock,
        new_stock=new_stock,
        exchange_brand=exchange_brand,
        exchange_link=exchange_link,
        exchange_product=exchange_product,
    )


def make_customers(count: int) -> list:
    return [create_user(role=UserRole.CUSTOMER) for _ in range(count)]


# --------------------------------------------------------------------------- #
# Passage de commandes via les services (source de vérité métier)
# --------------------------------------------------------------------------- #
def place_order(
    setup: OrderSetup,
    customer,
    *,
    operation_type=OperationType.REFILL,
    quantity=1,
    exchange_brand=AUTO,
    now=BASE_NOW,
):
    if exchange_brand is AUTO:
        exchange_brand = (
            setup.exchange_brand if operation_type == OperationType.EXCHANGE else None
        )
    return order_services.create_order(
        customer=customer,
        depot=setup.depot,
        product=setup.product,
        operation_type=operation_type,
        quantity=quantity,
        exchange_brand=exchange_brand,
        now=now,
    )


def make_order_in_state(
    setup: OrderSetup,
    customer,
    state,
    *,
    operation_type=OperationType.REFILL,
    quantity: int = 1,
    now: datetime = BASE_NOW,
):
    """Amène une commande dans l'état ``state`` en n'utilisant que les services.

    Chronologie (relative à ``now`` = 10:00 par défaut) :
    création 10:00 -> acceptation 10:05 (retrait limite 12:05) -> retrait 10:30 ;
    refus / annulation 10:05 ; expiration PENDING constatée à 10:20.
    """
    order = place_order(
        setup, customer, operation_type=operation_type, quantity=quantity, now=now
    )
    actor = setup.manager
    if state == OrderStatus.PENDING:
        pass
    elif state == OrderStatus.CONFIRMED:
        order_services.accept_order(order=order, actor=actor, now=now + timedelta(minutes=5))
    elif state == OrderStatus.PICKED_UP:
        order_services.accept_order(order=order, actor=actor, now=now + timedelta(minutes=5))
        order_services.complete_pickup(
            order=order,
            actor=actor,
            payment_method=PaymentMethod.CASH,
            now=now + timedelta(minutes=30),
        )
    elif state == OrderStatus.REFUSED:
        order_services.refuse_order(
            order=order, actor=actor, reason="Rupture de stock", now=now + timedelta(minutes=5)
        )
    elif state == OrderStatus.CANCELLED:
        order_services.cancel_order_by_customer(
            order=order, customer=customer, now=now + timedelta(minutes=5)
        )
    elif state == OrderStatus.EXPIRED:
        order_services.expire_order(order=order, now=now + timedelta(minutes=20))
    else:  # pragma: no cover
        raise ValueError(f"État inconnu : {state}")
    return Order.objects.get(pk=order.pk)


def make_cancelled_orders(setup: OrderSetup, customer, count: int, *, now=BASE_NOW) -> list:
    """``count`` commandes finales (CANCELLED) pour un même client."""
    orders = []
    for _ in range(count):
        order = place_order(setup, customer, now=now)
        order_services.cancel_order_by_customer(
            order=order, customer=customer, now=now + timedelta(minutes=1)
        )
        orders.append(Order.objects.get(pk=order.pk))
    return orders


# --------------------------------------------------------------------------- #
# Suspension client (noms de champs introspectés : non garantis par le contrat)
# --------------------------------------------------------------------------- #
def _concrete_names(model) -> set[str]:
    return {f.name for f in model._meta.get_fields() if getattr(f, "concrete", False)}


def _first_present(names: set[str], *candidates: str) -> str | None:
    return next((c for c in candidates if c in names), None)


def make_suspension(customer, *, starts_at, ends_at, lifted_at=None, reason=None):
    names = _concrete_names(CustomerSuspension)
    owner = _first_present(names, "customer", "user")
    end = _first_present(names, "ends_at", "end_at", "expires_at")
    if owner is None or end is None:  # pragma: no cover
        raise RuntimeError(
            "CustomerSuspension : champs client/fin introuvables, adapter make_suspension()."
        )
    data = {owner: customer, end: ends_at}
    start = _first_present(names, "starts_at", "started_at", "start_at", "begins_at")
    if start:
        data[start] = starts_at
    if "lifted_at" in names:
        data["lifted_at"] = lifted_at
    if "reason" in names:
        data["reason"] = reason or list(SuspensionReason)[0]
    return CustomerSuspension.objects.create(**data)


# --------------------------------------------------------------------------- #
# Lecture d'état
# --------------------------------------------------------------------------- #
def stock_of(depot, product, category=StockCategory.FULL) -> DepotStock:
    return DepotStock.objects.get(depot=depot, product=product, category=category)


def available(stock: DepotStock) -> int:
    return stock.physical_quantity - stock.reserved_quantity


def reservations_of(order):
    return StockReservation.objects.filter(order=order)


def movement_type_field() -> str:
    names = _concrete_names(StockMovement)
    name = _first_present(names, "movement_type", "type", "kind", "movement_kind")
    if name is None:  # pragma: no cover
        raise RuntimeError("StockMovement : champ de type introuvable, adapter movement_type_field().")
    return name


def movements(movement_type):
    return StockMovement.objects.filter(**{movement_type_field(): movement_type})


def history_of(order) -> list[OrderStatusHistory]:
    ordering = "created_at" if "created_at" in _concrete_names(OrderStatusHistory) else "pk"
    return list(OrderStatusHistory.objects.filter(order=order).order_by(ordering, "pk"))


def clone_instance(obj):
    """Copie non sauvegardée d'une instance (nouvelle PK) — pour tester les contraintes d'unicité."""
    kwargs = {}
    for f in obj._meta.concrete_fields:
        if f.primary_key:
            kwargs[f.attname] = f.get_default() if f.has_default() else None
        else:
            kwargs[f.attname] = getattr(obj, f.attname)
    return obj.__class__(**kwargs)


__all__ = [
    "AUTO", "BASE_NOW", "CUSTOMER_ORDER_KEYS", "DEPOT_CUSTOMER_KEYS", "DEPOT_ORDER_KEYS",
    "DOUALA", "FORBIDDEN_PRIVACY_KEYS", "FROZEN_ISO", "NONEXISTENT_ID",
    "NON_PUBLISHED_STATUS", "ORDER_ITEM_KEYS", "OrderSetup", "PAYMENT_KEYS",
    "ProductStatus", "at", "available", "clone_instance", "error_code", "history_of",
    "make_cancelled_orders", "make_customers", "make_order_in_state", "make_order_setup",
    "make_suspension", "movement_type_field", "movements", "place_order",
    "reservations_of", "stock_of", "walk_keys",
]