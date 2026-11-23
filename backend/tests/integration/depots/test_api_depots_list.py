from datetime import time

import pytest
from django.utils import timezone

from apps.catalog.models import ProductStatus, ProductType
from apps.depots.models import DepotStatus, OperationType
from tests.constants import ERROR_KEYS
from tests.constants_j1 import URL_DEPOTS
from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import make_depot, make_offer, make_operation, make_exchange_brand
from tests.geo import AKWA, BONANJO
from tests.helpers import assert_unified_error
from tests.time_helpers import at_douala, douala

pytestmark = pytest.mark.integration


def _published_product(*, brand=None, capacity=12.5, product_type=ProductType.BUTANE):
    brand = brand or make_brand(is_active=True)
    return make_product(brand=brand, capacity_kg=capacity, product_type=product_type, status=ProductStatus.PUBLISHED)



def _active_depot(*, lat=None, lng=None, name=None, **kwargs):
    return make_depot(status=DepotStatus.ACTIVE, lat=lat, lng=lng, name=name, **kwargs)



@pytest.mark.django_db
def test_list_returns_paginated_shape_and_exact_depot_fields(api_client):
    with at_douala(2026, 6, 15, 10, 0):
        depot = _active_depot(lat=AKWA[0], lng=AKWA[1])
        response = api_client.get(URL_DEPOTS)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"count", "next", "previous", "results"}
        assert body["count"] >= 1
        item = next(row for row in body["results"] if row["id"] == str(depot.pk))
        assert set(item) == {
            "id", "name", "address", "neighborhood", "phone", "latitude", "longitude",
            "distance_meters", "opening_time", "closing_time", "open_status", "can_order",
            "last_order_time", "reopens_at", "offers", "updated_at",
        }
        assert item["distance_meters"] is None
        assert item["opening_time"] == "08:00:00"
        assert item["closing_time"] == "20:00:00"
        assert len(item["last_order_time"]) == 5
        assert len(item["reopens_at"]) == 5


@pytest.mark.django_db
def test_page_size_is_capped_at_50(api_client):
    for i in range(55):
        _active_depot(name=f"Depot pagination {i:02d}")
    response = api_client.get(URL_DEPOTS, {"page_size": 999})
    assert response.status_code == 200
    assert len(response.json()["results"]) == 50



@pytest.mark.django_db
def test_out_of_range_page_returns_unified_404(api_client):
    response = api_client.get(URL_DEPOTS, {"page": 999999})
    assert_unified_error(response, status=404)
    assert set(response.json()) == ERROR_KEYS



@pytest.mark.django_db
def test_distance_meters_is_integer_when_coordinates_supplied(api_client):
    depot = _active_depot(lat=AKWA[0], lng=AKWA[1])
    response = api_client.get(URL_DEPOTS, {"lat": AKWA[0], "lng": AKWA[1]})
    assert response.status_code == 200
    item = next(row for row in response.json()["results"] if row["id"] == str(depot.pk))
    assert isinstance(item["distance_meters"], int)
    assert item["distance_meters"] == 0



@pytest.mark.django_db
def test_active_offer_without_active_operations_is_returned_with_empty_operations(api_client):
    product = _published_product()
    depot = _active_depot(lat=AKWA[0], lng=AKWA[1])
    offer = make_offer(depot, product, is_active=True)
    make_operation(offer, operation_type=OperationType.REFILL, is_active=False)
    response = api_client.get(URL_DEPOTS)
    assert response.status_code == 200
    item = next(row for row in response.json()["results"] if row["id"] == str(depot.pk))
    matching_offer = next(row for row in item["offers"] if row["id"] == str(offer.pk))
    assert matching_offer["operations"] == []



@pytest.mark.django_db
def test_offer_nested_serialization_has_expected_fields(api_client):
    brand = make_brand(is_active=True)
    product = _published_product(brand=brand)
    depot = _active_depot(lat=AKWA[0], lng=AKWA[1])
    offer = make_offer(depot, product, is_active=True, notes="Offer notes")
    make_operation(offer, operation_type=OperationType.REFILL, gas_price=1200, is_active=True)
    response = api_client.get(URL_DEPOTS)
    item = next(row for row in response.json()["results"] if row["id"] == str(depot.pk))
    serialized_offer = next(row for row in item["offers"] if row["id"] == str(offer.pk))
    assert set(serialized_offer) == {"id", "product", "notes", "operations", "exchange_brands", "updated_at"}
    assert len(serialized_offer["operations"]) == 1
    op = serialized_offer["operations"][0]
    assert set(op) == {"operation_type", "gas_price", "bottle_price", "deposit_amount", "total_unit_price"}
    assert op["gas_price"] == 1200
    assert op["total_unit_price"] == 1200



@pytest.mark.django_db
def test_exchange_brands_only_active_brands_are_exposed(api_client):
    primary_brand = make_brand(is_active=True)
    product = _published_product(brand=primary_brand)
    depot = _active_depot(lat=AKWA[0], lng=AKWA[1])
    offer = make_offer(depot, product)
    accepted_active = make_brand(is_active=True)
    accepted_inactive = make_brand(is_active=False)
    make_exchange_brand(offer, accepted_brand=accepted_active)
    make_exchange_brand(offer, accepted_brand=accepted_inactive)
    response = api_client.get(URL_DEPOTS)
    item = next(row for row in response.json()["results"] if row["id"] == str(depot.pk))
    serialized_offer = next(row for row in item["offers"] if row["id"] == str(offer.pk))
    ids = [entry.get("id") for entry in serialized_offer["exchange_brands"]]
    assert str(accepted_active.pk) in ids
    assert str(accepted_inactive.pk) not in ids



@pytest.mark.django_db
def test_public_list_ignores_invalid_or_expired_bearer_token(api_client):
    response = api_client.get(URL_DEPOTS, HTTP_AUTHORIZATION="Bearer invalid-or-expired-token")
    assert response.status_code == 200



@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.django_db
def test_write_methods_are_405_unified(api_client, method):
    response = getattr(api_client, method)(URL_DEPOTS, data={}, format="json")
    assert_unified_error(response, status=405)
    assert set(response.json()) == ERROR_KEYS



@pytest.mark.django_db
def test_search_q_matches_name_address_or_neighborhood(api_client):
    target = _active_depot(name="Unique Depot Query", address="Route de Bonanjo", neighborhood="Bonanjo")
    other = _active_depot(name="Unrelated Depot")
    response = api_client.get(URL_DEPOTS, {"q": "Bonanjo"})
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["results"]}
    assert str(target.pk) in ids
    assert str(other.pk) not in ids



@pytest.mark.django_db
def test_brand_capacity_and_operation_filters(api_client):
    brand = make_brand(is_active=True)
    product = _published_product(brand=brand, capacity=12.5)
    depot = _active_depot(lat=AKWA[0], lng=AKWA[1])
    offer = make_offer(depot, product)
    make_operation(offer, operation_type=OperationType.REFILL, is_active=True)
    response = api_client.get(URL_DEPOTS, {"brand": str(brand.pk), "capacity_kg": "12.50", "operation": "REFILL"})
    assert response.status_code == 200
    assert str(depot.pk) in {row["id"] for row in response.json()["results"]}



@pytest.mark.django_db
def test_open_now_excludes_depots_outside_opening_interval(api_client):
    with at_douala(2026, 6, 15, 10, 0):
        open_depot = make_depot(status=DepotStatus.ACTIVE, opening_time=time(8, 0), closing_time=time(20, 0))
        closed_depot = make_depot(status=DepotStatus.ACTIVE, opening_time=time(12, 0), closing_time=time(20, 0))
        response = api_client.get(URL_DEPOTS, {"open_now": "true"})
        assert response.status_code == 200
        ids = {row["id"] for row in response.json()["results"]}
        assert str(open_depot.pk) in ids
        assert str(closed_depot.pk) not in ids


@pytest.mark.django_db
def test_open_depots_are_sorted_before_closed_even_if_closed_is_closer(api_client):
    with at_douala(2026, 6, 15, 10, 0):
        closer_closed = _active_depot(lat=AKWA[0], lng=AKWA[1], name="A closer closed depot", opening_time=time(12, 0), closing_time=time(20, 0))
        farther_open = _active_depot(lat=BONANJO[0], lng=BONANJO[1], name="Z farther open depot", opening_time=time(8, 0), closing_time=time(20, 0))
        response = api_client.get(URL_DEPOTS, {"lat": AKWA[0], "lng": AKWA[1]})
        assert response.status_code == 200
        ids = [row["id"] for row in response.json()["results"]]
        assert ids.index(str(farther_open.pk)) < ids.index(str(closer_closed.pk))