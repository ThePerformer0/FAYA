"""Black-box integration tests for manager offers and pricing operations (Lot 4)."""
from decimal import Decimal
import pytest
from apps.catalog.models import ProductStatus, ProductType
from apps.depots.models import DepotStatus, OperationType
from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import make_depot, make_offer, make_operation, make_exchange_brand
from tests.helpers import assert_unified_error
pytestmark = pytest.mark.django_db
URL = "/api/v1/depot/offers/"


def _depot(manager):
    try:
        return manager.depot
    except Exception:
        return make_depot(manager=manager)

def _product(brand=None):
    brand = brand or make_brand()
    return make_product(brand=brand, status=ProductStatus.PUBLISHED, product_type=ProductType.BUTANE)

def _create_payload(product, **extra):
    payload = {"product_id": str(product.pk), "is_active": True, "notes": "Test offer"}
    payload.update(extra)
    return payload


def test_list_offers_includes_active_and_inactive_and_contract(auth_client, depot_manager):
    depot = _depot(depot_manager)
    p_active, p_inactive = _product(), _product()
    make_offer(depot=depot, product=p_active, is_active=True)
    make_offer(depot=depot, product=p_inactive, is_active=False)
    response = auth_client(depot_manager).get(URL)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"count", "next", "previous", "results"}
    ids = {x["product"].get("id") if isinstance(x["product"], dict) else x["product"] for x in body["results"]}
    assert str(p_active.pk) in ids and str(p_inactive.pk) in ids
    item = body["results"][0]
    assert set(item) == {"id", "product", "is_active", "notes", "operations", "exchange_brands", "created_at", "updated_at"}
    if item["operations"]:
        assert set(item["operations"][0]) == {"id", "operation_type", "is_active", "gas_price", "bottle_price", "deposit_amount", "total_unit_price"}
    assert response.headers.get("Cache-Control", "").lower().find("no-store") >= 0


def test_create_offer_with_operations_returns_201(auth_client, depot_manager):
    depot = _depot(depot_manager)
    product = _product()
    payload = _create_payload(product, operations=[{"operation_type": OperationType.REFILL, "gas_price": 1500}, {"operation_type": OperationType.FIRST_ACQUISITION, "gas_price": 1500, "bottle_price": 5000, "deposit_amount": 1000}])
    response = auth_client(depot_manager).post(URL, payload, format="json")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "product", "is_active", "notes", "operations", "exchange_brands", "created_at", "updated_at"}
    first = next(x for x in body["operations"] if x["operation_type"] == OperationType.FIRST_ACQUISITION)
    assert first["total_unit_price"] == first["gas_price"] + first["bottle_price"] + first["deposit_amount"]


def test_duplicate_offer_returns_conflict(auth_client, depot_manager):
    depot = _depot(depot_manager)
    product = _product()
    make_offer(depot=depot, product=product)
    response = auth_client(depot_manager).post(URL, _create_payload(product), format="json")
    assert_unified_error(response, status=409, code="OFFER_ALREADY_EXISTS")


@pytest.mark.parametrize("operations", [[{"operation_type": OperationType.REFILL, "gas_price": 100}, {"operation_type": OperationType.REFILL, "gas_price": 200}], [{"operation_type": OperationType.REFILL, "gas_price": 100, "bottle_price": 5}], [{"operation_type": OperationType.EXCHANGE, "gas_price": 100, "deposit_amount": 5}]])
def test_invalid_operation_combinations_rejected(auth_client, depot_manager, operations):
    _depot(depot_manager)
    response = auth_client(depot_manager).post(URL, _create_payload(_product(), operations=operations), format="json")
    assert_unified_error(response, status=400)


def test_exchange_brand_validation_and_duplicate_deduplication(auth_client, depot_manager):
    depot = _depot(depot_manager)
    product_brand = make_brand(name="Own product brand")
    own_product = _product(brand=product_brand)
    other_own_product = make_product(brand=product_brand, capacity_kg=Decimal("6.0"), status=ProductStatus.PUBLISHED, product_type=ProductType.BUTANE)
    accepted = make_brand(name="Accepted exchange brand")
    payload = _create_payload(own_product, exchange_brand_ids=[str(accepted.pk), str(accepted.pk)])
    response = auth_client(depot_manager).post(URL, payload, format="json")
    assert response.status_code == 201
    assert len(response.json()["exchange_brands"]) == 1
    invalid = auth_client(depot_manager).post(URL, _create_payload(_product(), exchange_brand_ids=["00000000-0000-0000-0000-000000000000"]), format="json")
    assert_unified_error(invalid, status=400)
    own_brand_rejected = auth_client(depot_manager).post(URL, _create_payload(other_own_product, exchange_brand_ids=[str(product_brand.pk)]), format="json")
    assert_unified_error(own_brand_rejected, status=400)


def test_offer_detail_get_patch_and_delete(auth_client, depot_manager):
    depot = _depot(depot_manager)
    offer = make_offer(depot=depot, product=_product(), is_active=True, notes="Original")
    make_operation(offer=offer, operation_type=OperationType.REFILL, gas_price=1200)
    client = auth_client(depot_manager)
    detail = URL + str(offer.pk) + "/"
    get_response = client.get(detail)
    assert get_response.status_code == 200
    patch_response = client.patch(detail, {"notes": "Changed", "is_active": False}, format="json")
    assert patch_response.status_code == 200
    assert patch_response.json()["notes"] == "Changed" and patch_response.json()["is_active"] is False
    deleted = client.delete(detail)
    assert deleted.status_code == 204 and not deleted.content


def test_offer_patch_operations_omitted_preserves_and_empty_clears(auth_client, depot_manager):
    depot = _depot(depot_manager)
    offer = make_offer(depot=depot, product=_product())
    make_operation(offer=offer, operation_type=OperationType.REFILL, gas_price=1000)
    detail = URL + str(offer.pk) + "/"
    client = auth_client(depot_manager)
    preserved = client.patch(detail, {"notes": "Only notes"}, format="json")
    assert preserved.status_code == 200 and len(preserved.json()["operations"]) == 1
    cleared = client.patch(detail, {"operations": []}, format="json")
    assert cleared.status_code == 200 and cleared.json()["operations"] == []


def test_foreign_offer_is_not_disclosed(auth_client, depot_manager, other_customer):
    depot_a = _depot(depot_manager)
    manager_b = other_customer
    depot_b = make_depot(manager=manager_b)
    offer_b = make_offer(depot=depot_b, product=_product())
    detail = URL + str(offer_b.pk) + "/"
    for method, data in [("get", None), ("patch", {"notes": "intrusion"}), ("delete", None)]:
        response = getattr(auth_client(depot_manager), method)(detail, data, format="json") if method == "patch" else getattr(auth_client(depot_manager), method)(detail)
        assert_unified_error(response, status=404, code="NOT_FOUND")


@pytest.mark.parametrize("status", [DepotStatus.SUSPENDED, DepotStatus.DISABLED])
def test_noneditable_depot_cannot_mutate_own_offer(auth_client, depot_manager, status):
    depot = _depot(depot_manager)
    depot.status = status
    depot.save(update_fields=["status"])
    offer = make_offer(depot=depot, product=_product())
    detail = URL + str(offer.pk) + "/"
    for method, data in [("patch", {"notes": "blocked"}), ("delete", None)]:
        response = getattr(auth_client(depot_manager), method)(detail, data, format="json") if method == "patch" else auth_client(depot_manager).delete(detail)
        assert_unified_error(response, status=403, code="DEPOT_NOT_EDITABLE")
