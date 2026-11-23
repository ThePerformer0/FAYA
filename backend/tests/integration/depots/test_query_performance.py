"""Regression tests for query growth on public catalogue/depot endpoints."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tests.constants_j1 import URL_PRODUCTS, URL_DEPOTS, url_depot
from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import (
    make_depot, make_offer, make_operation, make_exchange_brand,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _populate_depot_graph(count, *, prefix="A"):
    """Create depots with a deliberately rich, similarly-shaped relation graph."""
    brands = [make_brand(name=f"Perf {prefix} brand {i}") for i in range(3)]
    products = [
        make_product(brand=brands[i % 3], capacity_kg=f"{12 + i}.50")
        for i in range(count * 2)
    ]
    exchange_brands = [make_brand(name=f"Exchange {prefix} {i}") for i in range(3)]
    depots = []
    for i in range(count):
        depot = make_depot(name=f"Performance {prefix} depot {i:02d}")
        depots.append(depot)
        for j in range(2):
            offer = make_offer(depot, product=products[i * 2 + j])
            make_operation(offer, gas_price=1000 + j)
            make_exchange_brand(offer, accepted_brand=exchange_brands[j])
    return depots


def _query_count(client, url):
    # Capture SQL without assuming a fixed baseline across Django/PostGIS versions.
    with CaptureQueriesContext(connection) as captured:
        response = client.get(url, format="json")
    assert response.status_code == 200, response.content
    return len(captured), response


def test_depot_list_has_constant_query_count_as_result_set_grows(
    api_client
):
    _populate_depot_graph(1, prefix="A")
    one_count, _ = _query_count(api_client, URL_DEPOTS)

    _populate_depot_graph(14, prefix="B")
    many_count, response = _query_count(api_client, URL_DEPOTS)

    assert response.data["count"] == 15
    assert many_count <= one_count + 1, (
        f"Query count grew with depot count: 1 depot={one_count}, 15 depots={many_count}"
    )


def test_depot_detail_query_count_does_not_grow_with_nested_offers(api_client):
    depot = make_depot(name="Detail performance depot")
    brand = make_brand(name="Detail base brand")
    exchange = make_brand(name="Detail base exchange")
    product = make_product(brand=brand, capacity_kg="12.50")
    offer = make_offer(depot, product=product)
    make_operation(offer, gas_price=1200)
    make_exchange_brand(offer, accepted_brand=exchange)
    one_count, _ = _query_count(api_client, url_depot(depot.pk))

    for index in range(1, 10):
        product_brand = make_brand(name=f"Detail product brand {index}")
        exchange_brand = make_brand(name=f"Detail exchange brand {index}")
        product = make_product(brand=product_brand, capacity_kg="12.50")
        offer = make_offer(depot, product=product)
        make_operation(offer, gas_price=1200 + index)
        make_exchange_brand(offer, accepted_brand=exchange_brand)

    many_count, response = _query_count(api_client, url_depot(depot.pk))
    assert len(response.data["offers"]) == 10
    assert many_count <= one_count + 1, (
        f"Detail query count grew with nested offers: 1 offer={one_count}, "
        f"10 offers={many_count}"
    )


def test_catalog_products_query_count_does_not_grow_with_products(
    api_client
):
    brand = make_brand(name="Product performance brand")
    make_product(brand=brand, capacity_kg="12.50")
    one_count, _ = _query_count(api_client, URL_PRODUCTS)

    for i in range(1, 15):
        make_product(brand=brand, capacity_kg=f"{20 + i}.50")
    many_count, response = _query_count(api_client, URL_PRODUCTS)

    assert response.data["count"] == 15
    assert many_count <= one_count + 1, (
        f"Product query count grew: 1 product={one_count}, 15 products={many_count}"
    )
