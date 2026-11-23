"""Fabriques catalogue : marques, produits, propositions."""
import itertools
from decimal import Decimal

from apps.catalog.models import (
    Brand,
    Product,
    ProductProposal,
    ProductProposalStatus,
    ProductStatus,
    ProductType,
)

_n = itertools.count(1)


def make_brand(*, name=None, is_active=True, logo_url="", **extra):
    return Brand.objects.create(
        name=f"Marque {next(_n)}" if name is None else name,
        is_active=is_active,
        logo_url=logo_url,
        **extra,
    )


def make_product(
    *,
    brand=None,
    capacity_kg=Decimal("12.5"),
    product_type=ProductType.BUTANE,
    status=ProductStatus.PUBLISHED,
    name=None,
    **extra,
):
    n = next(_n)
    extra.setdefault("description", "")
    extra.setdefault("characteristics", {})
    extra.setdefault("image_url", "")
    return Product.objects.create(
        brand=brand or make_brand(),
        capacity_kg=Decimal(str(capacity_kg)),
        product_type=product_type,
        status=status,
        name=f"Bouteille {n}" if name is None else name,
        **extra,
    )


def make_proposal(
    *,
    depot=None,
    proposed_brand_name=None,
    capacity_kg=Decimal("12.5"),
    product_type=ProductType.BUTANE,
    name=None,
    status=ProductProposalStatus.PENDING,
    **extra,
):
    from tests.factories_depots import make_depot

    n = next(_n)
    extra.setdefault("description", "")
    return ProductProposal.objects.create(
        depot=depot or make_depot(),
        proposed_brand_name=f"Nouvelle Marque {n}" if proposed_brand_name is None else proposed_brand_name,
        capacity_kg=Decimal(str(capacity_kg)),
        product_type=product_type,
        name=f"Proposition {n}" if name is None else name,
        status=status,
        **extra,
    )