"""Black-box integration tests for the depot stock API (Lot 3)."""
from decimal import Decimal
import pytest
from django.urls import reverse
from apps.catalog.models import ProductStatus, ProductType
from apps.depots.models import DepotStatus
from apps.inventory.models import StockCategory
from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import make_depot
from tests.factories_inventory import make_stock
from tests.helpers import assert_unified_error


pytestmark = pytest.mark.django_db
BASE = "/api/v1/depot/stocks/"
RESTOCK = BASE + "restock/"
ADJUST = BASE + "adjust/"
SCRAP = BASE + "scrap/"
MAX_STOCK = 2_147_483_647


def _depot_for(manager):
    try:
        return manager.depot
    except Exception:
        return make_depot(manager=manager)


def _product():
    brand = make_brand()
    return make_product(brand=brand, status=ProductStatus.PUBLISHED, product_type=ProductType.BUTANE)



def _auth(auth_client, manager):
    return auth_client(manager)



def _payload(product, category=StockCategory.FULL, quantity=3, reason="Test restock"):
    return {"product_id": str(product.pk), "category": category, "quantity": quantity, "reason": reason}



def _assert_stock_item(item):
    assert set(item) == {"id", "product", "category", "physical_quantity", "reserved_quantity", "available_quantity", "updated_at"}
    if item["category"] == StockCategory.EMPTY:
        assert item["available_quantity"] == 0
    else:
        assert item["available_quantity"] == item["physical_quantity"] - item["reserved_quantity"]



def test_list_stocks_has_pagination_and_contract(auth_client, depot_manager):
    depot = _depot_for(depot_manager)
    product = _product()
    make_stock(depot=depot, product=product, category=StockCategory.FULL, physical_quantity=8, reserved_quantity=2)
    response = _auth(auth_client, depot_manager).get(BASE)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"count", "next", "previous", "results"}
    assert body["count"] >= 1
    item = next(x for x in body["results"] if x["product"] == str(product.pk) or x["product"].get("id") == str(product.pk))
    _assert_stock_item(item)
    assert item["physical_quantity"] == 8
    assert item["reserved_quantity"] == 2
    assert item["available_quantity"] == 6
    assert response.headers.get("Cache-Control", "").lower().find("no-store") >= 0



def test_filter_by_product_and_category(auth_client, depot_manager):
    depot = _depot_for(depot_manager)
    p1, p2 = _product(), _product()
    make_stock(depot=depot, product=p1, category=StockCategory.FULL, physical_quantity=4)
    make_stock(depot=depot, product=p1, category=StockCategory.EMPTY, physical_quantity=9)
    make_stock(depot=depot, product=p2, category=StockCategory.FULL, physical_quantity=7)
    client = _auth(auth_client, depot_manager)
    by_product = client.get(BASE, {"product": str(p1.pk)})
    assert by_product.status_code == 200
    assert all((x["product"] == str(p1.pk) or x["product"].get("id") == str(p1.pk)) for x in by_product.json()["results"])
    by_category = client.get(BASE, {"category": StockCategory.EMPTY})
    assert by_category.status_code == 200
    assert all(x["category"] == StockCategory.EMPTY for x in by_category.json()["results"])


@pytest.mark.parametrize("query", ["?product=", "?category=", "?product=not-a-uuid", "?category=BOGUS"])
def test_invalid_stock_filters_are_400(auth_client, depot_manager, query):
    _depot_for(depot_manager)
    response = _auth(auth_client, depot_manager).get(BASE + query)
    assert_unified_error(response, status=400)



def test_restock_creates_stock_and_movement(auth_client, depot_manager):
    depot = _depot_for(depot_manager)
    product = _product()
    response = _auth(auth_client, depot_manager).post(RESTOCK, _payload(product), format="json")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"stock", "movement"}
    assert body["stock"]["physical_quantity"] == 3
    assert body["movement"]["delta"] == 3
    assert body["movement"]["quantity_after"] == 3
    assert body["stock"]["category"] == StockCategory.FULL
    assert response.headers.get("Cache-Control", "").lower().find("no-store") >= 0


@pytest.mark.parametrize("quantity", [0, -1, MAX_STOCK + 1, True, "3"])
def test_restock_rejects_invalid_quantity(auth_client, depot_manager, quantity):
    _depot_for(depot_manager)
    response = _auth(auth_client, depot_manager).post(RESTOCK, _payload(_product(), quantity=quantity), format="json")
    assert_unified_error(response, status=400)



def test_restock_unknown_product_is_404(auth_client, depot_manager):
    _depot_for(depot_manager)
    response = _auth(auth_client, depot_manager).post(RESTOCK, {"product_id": "00000000-0000-0000-0000-000000000000", "category": StockCategory.FULL, "quantity": 1}, format="json")
    assert_unified_error(response, status=404, code="NOT_FOUND")



def test_adjust_success_and_conflict_contract(auth_client, depot_manager):
    depot = _depot_for(depot_manager)
    product = _product()
    make_stock(depot=depot, product=product, category=StockCategory.FULL, physical_quantity=10, reserved_quantity=2)
    client = _auth(auth_client, depot_manager)
    success = client.post(ADJUST, {"product_id": str(product.pk), "category": StockCategory.FULL, "new_physical_quantity": 9, "reason": "Inventory count", "expected_physical_quantity": 10}, format="json")
    assert success.status_code == 200
    assert success.json()["stock"]["physical_quantity"] == 9
    conflict = client.post(ADJUST, {"product_id": str(product.pk), "category": StockCategory.FULL, "new_physical_quantity": 8, "reason": "Concurrent count", "expected_physical_quantity": 10}, format="json")
    assert_unified_error(conflict, status=409, code="STOCK_CONFLICT")
    assert "current_physical_quantity" in conflict.json()["details"]


@pytest.mark.parametrize("new_quantity", [-1, MAX_STOCK + 1, True, "5"])
def test_adjust_rejects_out_of_range_quantity(auth_client, depot_manager, new_quantity):
    _depot_for(depot_manager)
    response = _auth(auth_client, depot_manager).post(ADJUST, {"product_id": str(_product().pk), "category": StockCategory.FULL, "new_physical_quantity": new_quantity, "reason": "Count"}, format="json")
    assert_unified_error(response, status=400)



def test_adjust_below_reserved_returns_conflict(auth_client, depot_manager):
    depot = _depot_for(depot_manager)
    product = _product()
    make_stock(depot=depot, product=product, category=StockCategory.FULL, physical_quantity=8, reserved_quantity=4)
    response = _auth(auth_client, depot_manager).post(ADJUST, {"product_id": str(product.pk), "category": StockCategory.FULL, "new_physical_quantity": 3, "reason": "Count below reservations"}, format="json")
    assert_unified_error(response, status=409, code="STOCK_BELOW_RESERVED")
    assert "reserved_quantity" in response.json()["details"]



def test_adjust_unchanged_quantity_is_conflict(auth_client, depot_manager):
    depot = _depot_for(depot_manager)
    product = _product()
    make_stock(depot=depot, product=product, category=StockCategory.FULL, physical_quantity=5)
    response = _auth(auth_client, depot_manager).post(ADJUST, {"product_id": str(product.pk), "category": StockCategory.FULL, "new_physical_quantity": 5, "reason": "No change"}, format="json")
    assert_unified_error(response, status=409, code="STOCK_UNCHANGED")



def test_scrap_success_and_insufficient_stock_error(auth_client, depot_manager):
    depot = _depot_for(depot_manager)
    product = _product()
    make_stock(depot=depot, product=product, category=StockCategory.FULL, physical_quantity=8, reserved_quantity=2)
    client = _auth(auth_client, depot_manager)
    ok = client.post(SCRAP, {"product_id": str(product.pk), "category": StockCategory.FULL, "quantity": 2, "reason": "Damaged bottles"}, format="json")
    assert ok.status_code == 200
    assert ok.json()["stock"]["physical_quantity"] == 6
    fail = client.post(SCRAP, {"product_id": str(product.pk), "category": StockCategory.FULL, "quantity": 10, "reason": "Too many"}, format="json")
    assert_unified_error(fail, status=409, code="INSUFFICIENT_STOCK_FOR_SCRAP")
    assert "physical_quantity" in fail.json()["details"]
    assert "reserved_quantity" in fail.json()["details"]


@pytest.mark.parametrize("method,path", [("put", BASE), ("patch", BASE), ("delete", BASE), ("put", RESTOCK), ("patch", RESTOCK), ("delete", RESTOCK), ("put", ADJUST), ("patch", ADJUST), ("delete", ADJUST), ("put", SCRAP), ("patch", SCRAP), ("delete", SCRAP), ("post", BASE)])
def test_unsupported_methods_return_405(auth_client, depot_manager, method, path):
    _depot_for(depot_manager)
    response = getattr(_auth(auth_client, depot_manager), method)(path, {}, format="json")
    assert response.status_code == 405
