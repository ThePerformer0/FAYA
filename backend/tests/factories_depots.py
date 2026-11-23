"""Fabriques dépôts : dépôt, offre, opérations, marques d'échange."""
import itertools
from datetime import time

from apps.accounts.models import UserRole
from apps.depots.models import (
    Depot,
    DepotProductOffer,
    DepotStatus,
    OfferExchangeBrand,
    OfferOperation,
    OperationType,
)
from tests.factories_catalog import make_brand, make_product
from tests.geo import DOUALA_CENTER, point
from tests.helpers import create_user

_n = itertools.count(1)


def make_depot_manager(**extra):
    return create_user(role=UserRole.DEPOT_MANAGER, **extra)


def make_depot(
    *,
    manager=None,
    name=None,
    status=DepotStatus.ACTIVE,
    lat=None,
    lng=None,
    location=None,
    opening_time=time(8, 0),
    closing_time=time(20, 0),
    neighborhood="Akwa",
    address=None,
    description="",
    phone=None,
    **extra,
):
    """Dépôt ACTIVE de 08:00 à 20:00 au centre de Douala par défaut."""
    n = next(_n)
    if location is None:
        default_lat, default_lng = DOUALA_CENTER
        location = point(default_lat if lat is None else lat, default_lng if lng is None else lng)
    return Depot.objects.create(
        manager=manager or make_depot_manager(),
        name=name or f"Dépôt {n}",
        description=description,
        address=address or f"{n} rue de test",
        neighborhood=neighborhood,
        phone=phone or f"+2376{n:08d}",
        location=location,
        opening_time=opening_time,
        closing_time=closing_time,
        status=status,
        **extra,
    )


def make_offer(depot, product=None, *, is_active=True, notes="", **extra):
    return DepotProductOffer.objects.create(
        depot=depot, product=product or make_product(), is_active=is_active, notes=notes, **extra
    )


def make_operation(
    offer,
    operation_type=OperationType.REFILL,
    *,
    gas_price=1000,
    bottle_price=None,
    deposit_amount=None,
    is_active=True,
):
    """bottle_price / deposit_amount ne sont non nuls que pour FIRST_ACQUISITION (contrainte SQL)."""
    first = operation_type == OperationType.FIRST_ACQUISITION
    if bottle_price is None:
        bottle_price = 5000 if first else 0
    if deposit_amount is None:
        deposit_amount = 2000 if first else 0
    return OfferOperation.objects.create(
        offer=offer,
        operation_type=operation_type,
        gas_price=gas_price,
        bottle_price=bottle_price,
        deposit_amount=deposit_amount,
        is_active=is_active,
    )


def make_exchange_brand(offer, accepted_brand=None):
    return OfferExchangeBrand.objects.create(
        offer=offer, accepted_brand=accepted_brand or make_brand()
    )