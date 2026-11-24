"""Black-box integration tests for stock movement history (Lot 3)."""
import pytest
from apps.catalog.models import ProductStatus, ProductType
from apps.inventory.models import StockCategory, StockMovementType
from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import make_depot
from tests.factories_inventory import make_movement
from tests.helpers import assert_unified_error

pytestmark = pytest.mark.django_db
URL = "/api/v1/depot/stock-movements/"


def _depot(manager):
    try:
        return manager.depot
    except Exception:
        return make_depot(manager=manager)


def _product():
    return make_product(brand=make_brand(), status=ProductStatus.PUBLISHED, product_type=ProductType.BUTANE)



def test_movements_list_contract_and_actor_privacy(auth_client, depot_manager):
    depot = _depot(depot_manager)
    product = _product()
    movement = make_movement(depot=depot, product=product, category=StockCategory.FULL, movement_type=StockMovementType.RESTOCK, quantity_before=0, delta=4, quantity_after=4, actor=depot_manager, reason="Incoming stock")
    response = auth_client(depot_manager).get(URL)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"count", "next", "previous", "results"}
    item = next(x for x in body["results"] if x["id"] == str(movement.pk))
    assert set(item) == {"id", "product", "category", "movement_type", "quantity_before", "quantity_after", "delta", "reason", "actor_name", "created_at"}
    assert item["category"] == StockCategory.FULL
    assert item["movement_type"] == StockMovementType.RESTOCK
    assert item["quantity_before"] == 0 and item["quantity_after"] == 4 and item["delta"] == 4
    assert item["actor_name"] == depot_manager.full_name
    assert "email" not in item and "phone" not in item and "actor" not in item
    assert response.headers.get("Cache-Control", "").lower().find("no-store") >= 0


def test_movement_with_null_actor_exposes_null_actor_name(auth_client, depot_manager):
    depot = _depot(depot_manager)
    movement = make_movement(depot=depot, product=_product(), category=StockCategory.EMPTY, movement_type=StockMovementType.RESTOCK, quantity_before=0, delta=2, quantity_after=2, actor=None)
    response = auth_client(depot_manager).get(URL)
    assert response.status_code == 200
    item = next(x for x in response.json()["results"] if x["id"] == str(movement.pk))
    assert item["actor_name"] is None


def test_combined_movement_filters(auth_client, depot_manager):
    depot = _depot(depot_manager)
    p1, p2 = _product(), _product()
    m1 = make_movement(depot=depot, product=p1, category=StockCategory.FULL, movement_type=StockMovementType.RESTOCK, quantity_before=0, delta=4, quantity_after=4)
    make_movement(depot=depot, product=p2, category=StockCategory.EMPTY, movement_type=StockMovementType.SCRAP, quantity_before=3, delta=-1, quantity_after=2)
    response = auth_client(depot_manager).get(URL, {"product": str(p1.pk), "category": StockCategory.FULL, "movement_type": StockMovementType.RESTOCK})
    assert response.status_code == 200
    results = response.json()["results"]
    assert len(results) == 1 and results[0]["id"] == str(m1.pk)


@pytest.mark.parametrize("query", ["?product=", "?category=", "?movement_type=", "?product=bad-uuid", "?category=INVALID", "?movement_type=INVALID"])
def test_invalid_movement_filters_are_400(auth_client, depot_manager, query):
    _depot(depot_manager)
    response = auth_client(depot_manager).get(URL + query)
    assert_unified_error(response, status=400)


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_movement_endpoint_is_read_only(auth_client, depot_manager, method):
    _depot(depot_manager)
    response = getattr(auth_client(depot_manager), method)(URL, {}, format="json")
    assert response.status_code == 405
