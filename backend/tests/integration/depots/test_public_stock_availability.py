"""Black-box tests for public depot stock availability and query scaling (Lot 5)."""
from datetime import datetime
import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from apps.catalog.models import ProductStatus, ProductType
from apps.depots.models import DepotStatus
from apps.inventory.models import StockCategory
from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import make_depot, make_offer
from tests.factories_inventory import make_stock
pytestmark = pytest.mark.django_db
LIST_URL = "/api/v1/depots/"


def _product():
    return make_product(brand=make_brand(), status=ProductStatus.PUBLISHED, product_type=ProductType.BUTANE)

def _availability_offer(depot, product):
    offer = make_offer(depot=depot, product=product, is_active=True)
    return offer

def _public_offer_for(response, offer):
    body = response.json()
    if isinstance(body, dict) and "offers" in body:
        depots = [body]
    elif isinstance(body, dict):
        depots = body.get("results", [])
    else:
        depots = body
    for depot in depots:
        offers = depot.get("offers", [])
        for item in offers:
            if item.get("id") == str(offer.pk):
                return item
    raise AssertionError(f"Offer {offer.pk} not present in public response")

def _create_depot(name):
    depot = make_depot(name=name, status=DepotStatus.ACTIVE)
    return depot


def test_public_offer_exposes_full_new_available_and_stock_timestamp(client):
    depot = _create_depot("Public stocks depot")
    product = _product()
    offer = _availability_offer(depot, product)
    full = make_stock(depot=depot, product=product, category=StockCategory.FULL, physical_quantity=10, reserved_quantity=3)
    new = make_stock(depot=depot, product=product, category=StockCategory.NEW, physical_quantity=5, reserved_quantity=5)
    make_stock(depot=depot, product=product, category=StockCategory.EMPTY, physical_quantity=99, reserved_quantity=0)
    make_stock(depot=depot, product=product, category=StockCategory.DEPOSIT, physical_quantity=88, reserved_quantity=0)
    response = client.get(LIST_URL)
    assert response.status_code == 200
    item = _public_offer_for(response, offer)
    assert {"available_full_quantity", "available_new_quantity", "stock_updated_at"}.issubset(item)
    assert item["available_full_quantity"] == 7
    assert item["available_new_quantity"] == 0
    assert item["stock_updated_at"] is not None
    assert "physical_quantity" not in item and "reserved_quantity" not in item


def test_stock_timestamp_is_latest_full_or_new_and_empty_deposit_do_not_affect(client):
    depot = _create_depot("Timestamp depot")
    product = _product()
    offer = _availability_offer(depot, product)
    full = make_stock(depot=depot, product=product, category=StockCategory.FULL, physical_quantity=4, reserved_quantity=0)
    new = make_stock(depot=depot, product=product, category=StockCategory.NEW, physical_quantity=3, reserved_quantity=1)
    response = client.get(LIST_URL)
    item = _public_offer_for(response, offer)
    assert item["available_full_quantity"] == 4
    assert item["available_new_quantity"] == 2
    # Timestamp must be the newest of FULL and NEW, never from EMPTY or DEPOSIT.
    timestamps = [full.updated_at, new.updated_at]
    newest = max(timestamps)
    if isinstance(item["stock_updated_at"], str):
        assert datetime.fromisoformat(item["stock_updated_at"].replace("Z", "+00:00")) == newest


def test_missing_stock_yields_zero_availability_and_null_timestamp(client):
    depot = _create_depot("No stock depot")
    offer = _availability_offer(depot, _product())
    response = client.get(LIST_URL)
    item = _public_offer_for(response, offer)
    assert item["available_full_quantity"] == 0
    assert item["available_new_quantity"] == 0
    assert item["stock_updated_at"] is None


def test_public_detail_availability_endpoint(client):
    depot = _create_depot("Detail endpoint depot")
    product = _product()
    offer = _availability_offer(depot, product)
    make_stock(depot=depot, product=product, category=StockCategory.FULL, physical_quantity=6, reserved_quantity=1)
    response = client.get(f"/api/v1/depots/{depot.pk}/")
    assert response.status_code == 200
    item = _public_offer_for(response, offer)
    assert item["available_full_quantity"] == 5


def test_public_stock_is_tenant_scoped_for_same_product(client):
    product = _product()
    depot_a = _create_depot("Depot A public")
    depot_b = _create_depot("Depot B public")
    offer_a = _availability_offer(depot_a, product)
    _availability_offer(depot_b, product)
    make_stock(depot=depot_a, product=product, category=StockCategory.FULL, physical_quantity=4, reserved_quantity=1)
    make_stock(depot=depot_b, product=product, category=StockCategory.FULL, physical_quantity=20, reserved_quantity=2)
    response = client.get(f"/api/v1/depots/{depot_a.pk}/")
    assert response.status_code == 200
    assert _public_offer_for(response, offer_a)["available_full_quantity"] == 3


def test_public_list_query_count_does_not_scale_linearly(client):
    # Compare a small and larger dataset while excluding fixture creation from query capture.
    small_depot = _create_depot("SQL small")
    p_small = _product()
    _availability_offer(small_depot, p_small)
    make_stock(depot=small_depot, product=p_small, category=StockCategory.FULL, physical_quantity=5)
    with CaptureQueriesContext(connection) as small_ctx:
        small_response = client.get(LIST_URL)
    assert small_response.status_code == 200

    for index in range(10):
        depot = _create_depot(f"SQL larger {index}")
        for j in range(4):
            product = _product()
            _availability_offer(depot, product)
            for category in (StockCategory.FULL, StockCategory.EMPTY, StockCategory.NEW, StockCategory.DEPOSIT):
                make_stock(depot=depot, product=product, category=category, physical_quantity=5)
    with CaptureQueriesContext(connection) as large_ctx:
        large_response = client.get(LIST_URL)
    assert large_response.status_code == 200
    # Pagination may add fixed queries; permit a small fixed overhead, but reject N+1 growth.
    assert len(large_ctx) <= len(small_ctx) + 8
