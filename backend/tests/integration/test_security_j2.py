"""Black-box security regression tests for the Jalon 2 depot API."""
import pytest
from apps.accounts.models import UserRole
from apps.catalog.models import ProductStatus, ProductType
from apps.depots.models import DepotStatus, OperationType
from apps.inventory.models import StockCategory, StockMovementType
from tests.helpers import create_user, assert_unified_error
from tests.factories_catalog import make_brand, make_product, make_proposal
from tests.factories_depots import make_depot, make_offer
from tests.factories_inventory import make_stock, make_movement
pytestmark = pytest.mark.django_db

# Endpoint/method pairs include every documented depot API surface.
GET_ENDPOINTS = [
    "/api/v1/depot/",
    "/api/v1/depot/offers/",
    "/api/v1/depot/proposals/",
    "/api/v1/depot/stocks/",
    "/api/v1/depot/stock-movements/",
]
MUTATION_ENDPOINTS = [
    ("post", "/api/v1/depot/offers/", {}),
    ("post", "/api/v1/depot/proposals/", {}),
    ("post", "/api/v1/depot/stocks/restock/", {}),
    ("post", "/api/v1/depot/stocks/adjust/", {}),
    ("post", "/api/v1/depot/stocks/scrap/", {}),
    ("patch", "/api/v1/depot/", {}),
]
ALL_DEPOT_PATHS = GET_ENDPOINTS + [x[1] for x in MUTATION_ENDPOINTS] + [
    "/api/v1/depot/offers/00000000-0000-0000-0000-000000000000/",
]


def _depot(manager, status=DepotStatus.ACTIVE):
    try:
        depot = manager.depot
        if status is not None and depot.status != status:
            depot.status = status
            depot.save(update_fields=["status"])
        return depot
    except Exception:
        return make_depot(manager=manager, status=status or DepotStatus.ACTIVE)

def _product():
    return make_product(brand=make_brand(), status=ProductStatus.PUBLISHED, product_type=ProductType.BUTANE)

def _user(role):
    return create_user(role=role)


@pytest.mark.parametrize("path", GET_ENDPOINTS)
def test_anonymous_get_is_401_and_cache_policy_is_present(api_client, path):
    response = api_client.get(path)
    assert response.status_code == 401
    assert response.headers.get("Cache-Control", "").lower().find("no-store") >= 0


@pytest.mark.parametrize("path", GET_ENDPOINTS + [x[1] for x in MUTATION_ENDPOINTS])
def test_customer_and_admin_are_forbidden(auth_client, customer, admin_user, path):
    for user in (customer, admin_user):
        method = "get" if path in GET_ENDPOINTS else "post"
        response = getattr(auth_client(user), method)(path, {}, format="json") if method == "post" else auth_client(user).get(path)
        assert response.status_code == 403
        assert response.headers.get("Cache-Control", "").lower().find("no-store") >= 0


def test_manager_without_depot_is_forbidden(auth_client):
    manager = _user(UserRole.DEPOT_MANAGER)
    for path in GET_ENDPOINTS:
        assert auth_client(manager).get(path).status_code == 403
    for method, path, body in MUTATION_ENDPOINTS:
        assert getattr(auth_client(manager), method)(path, body, format="json").status_code == 403


def test_disabled_account_is_unauthorized(auth_client, depot_manager):
    depot_manager.is_active = False
    depot_manager.save(update_fields=["is_active"])
    for path in GET_ENDPOINTS:
        assert auth_client(depot_manager).get(path).status_code == 401
    response = auth_client(depot_manager).patch("/api/v1/depot/", {"description": "disabled"}, format="json")
    assert response.status_code == 401


def test_depot_manager_gets_no_store_for_success_and_client_errors(auth_client, depot_manager):
    _depot(depot_manager)
    client = auth_client(depot_manager)
    success_paths = GET_ENDPOINTS
    for path in success_paths:
        response = client.get(path)
        assert response.status_code == 200
        assert "no-store" in response.headers.get("Cache-Control", "").lower()
    bad_query = client.get("/api/v1/depot/stocks/?category=invalid")
    assert bad_query.status_code == 400
    assert "no-store" in bad_query.headers.get("Cache-Control", "").lower()


def test_cross_tenant_offer_and_stock_records_are_not_exposed(auth_client, depot_manager, other_customer):
    depot_a = _depot(depot_manager)
    depot_b = make_depot(manager=other_customer, status=DepotStatus.ACTIVE)
    product_a, product_b = _product(), _product()
    offer_b = make_offer(depot=depot_b, product=product_b)
    make_stock(depot=depot_b, product=product_b, category=StockCategory.FULL, physical_quantity=23)
    make_movement(depot=depot_b, product=product_b, category=StockCategory.FULL, movement_type=StockMovementType.RESTOCK, quantity_before=0, delta=23, quantity_after=23)
    client = auth_client(depot_manager)
    offers = client.get("/api/v1/depot/offers/")
    assert offers.status_code == 200
    assert all(item["id"] != str(offer_b.pk) for item in offers.json()["results"])
    stocks = client.get("/api/v1/depot/stocks/")
    assert stocks.status_code == 200
    assert all(item["physical_quantity"] != 23 for item in stocks.json()["results"])
    movements = client.get("/api/v1/depot/stock-movements/")
    assert movements.status_code == 200
    assert all(item["quantity_after"] != 23 for item in movements.json()["results"])


def test_cross_tenant_offer_id_is_not_disclosed_even_when_manager_suspended(auth_client, depot_manager, other_customer):
    depot_a = _depot(depot_manager, status=DepotStatus.SUSPENDED)
    depot_b = make_depot(manager=other_customer)
    offer_b = make_offer(depot=depot_b, product=_product())
    detail = f"/api/v1/depot/offers/{offer_b.pk}/"
    for method in ("patch", "delete"):
        response = getattr(auth_client(depot_manager), method)(detail, {"notes": "attempt"}, format="json") if method == "patch" else auth_client(depot_manager).delete(detail)
        assert_unified_error(response, status=404, code="NOT_FOUND")


def test_tenant_injection_fields_do_not_change_depot_ownership(auth_client, depot_manager, other_customer):
    depot_a = _depot(depot_manager)
    depot_b = make_depot(manager=other_customer)
    original = depot_a.manager_id
    client = auth_client(depot_manager)
    response = client.patch("/api/v1/depot/", {"manager_id": other_customer.pk, "depot": depot_b.pk, "depot_id": depot_b.pk}, format="json")
    assert response.status_code == 200
    depot_a.refresh_from_db()
    assert depot_a.manager_id == original
    assert depot_a.manager_id != depot_b.manager_id


@pytest.mark.parametrize("path", [
    "/api/v1/depot/stocks/", "/api/v1/depot/stocks/restock/", "/api/v1/depot/stocks/adjust/", "/api/v1/depot/stocks/scrap/", "/api/v1/depot/stock-movements/",
])
@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_stock_endpoints_reject_unsupported_http_methods(auth_client, depot_manager, path, method):
    _depot(depot_manager)
    response = getattr(auth_client(depot_manager), method)(path, {}, format="json")
    assert response.status_code == 405


@pytest.mark.parametrize("bad_payload", [[], "not-an-object", {"product_id": "malformed", "category": "FULL", "quantity": True}, {"product_id": "00000000-0000-0000-0000-000000000000", "category": "FULL", "quantity": 1, "reason": "x" * 501}])
def test_hostile_stock_payloads_fail_cleanly(auth_client, depot_manager, bad_payload):
    _depot(depot_manager)
    response = auth_client(depot_manager).post("/api/v1/depot/stocks/restock/", bad_payload, format="json")
    assert response.status_code in (400, 404)
    assert response.headers.get("Cache-Control", "").lower().find("no-store") >= 0
    assert response.headers.get("Content-Type", "").startswith("application/json")
