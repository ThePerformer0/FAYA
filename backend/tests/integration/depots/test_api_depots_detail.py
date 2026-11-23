import pytest
from apps.catalog.models import ProductStatus, ProductType
from apps.depots.models import DepotStatus, OperationType
from tests.constants import ERROR_KEYS
from tests.constants_j1 import URL_DEPOTS, url_depot
from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import make_depot, make_offer, make_operation, make_exchange_brand
from tests.geo import AKWA
from tests.helpers import assert_unified_error

pytestmark = pytest.mark.integration


def _published_product(brand=None, capacity=12.5):
    brand = brand or make_brand(is_active=True)
    return make_product(brand=brand, capacity_kg=capacity, product_type=ProductType.BUTANE, status=ProductStatus.PUBLISHED)



@pytest.mark.django_db
def test_detail_has_exact_fields_description_and_no_distance(api_client):
    depot = make_depot(status=DepotStatus.ACTIVE, lat=AKWA[0], lng=AKWA[1], description="Public detail description")
    response = api_client.get(url_depot(depot.pk))
    assert response.status_code == 200
    item = response.json()
    assert "description" in item
    assert "distance_meters" not in item
    assert set(item) == {
        "id", "name", "address", "neighborhood", "phone", "latitude", "longitude",
        "opening_time", "closing_time", "open_status", "can_order", "last_order_time",
        "reopens_at", "offers", "updated_at", "description",
    }



@pytest.mark.django_db
def test_detail_filters_inactive_offers_unpublished_products_and_inactive_brands(api_client):
    depot = make_depot(status=DepotStatus.ACTIVE, lat=AKWA[0], lng=AKWA[1])
    brand_live = make_brand(is_active=True)
    brand_inactive = make_brand(is_active=False)
    published = make_product(brand=brand_live, capacity_kg=12.5, product_type=ProductType.BUTANE, status=ProductStatus.PUBLISHED)
    published_inactive_offer = make_product(brand=brand_live, capacity_kg=35.0, product_type=ProductType.BUTANE, status=ProductStatus.PUBLISHED)
    unpublished = make_product(brand=brand_live, capacity_kg=6.5, product_type=ProductType.BUTANE, status=ProductStatus.DRAFT)
    inactive_brand_product = make_product(brand=brand_inactive, capacity_kg=9.0, product_type=ProductType.BUTANE, status=ProductStatus.PUBLISHED)
    visible_offer = make_offer(depot, published, is_active=True)
    inactive_offer = make_offer(depot, published_inactive_offer, is_active=False)
    hidden_unpublished_offer = make_offer(depot, unpublished, is_active=True)
    hidden_brand_offer = make_offer(depot, inactive_brand_product, is_active=True)
    active_operation = make_operation(visible_offer, operation_type=OperationType.REFILL, is_active=True)
    inactive_operation = make_operation(visible_offer, operation_type=OperationType.EXCHANGE, is_active=False)
    accepted_live = make_brand(is_active=True)
    accepted_inactive = make_brand(is_active=False)
    make_exchange_brand(visible_offer, accepted_brand=accepted_live)
    make_exchange_brand(visible_offer, accepted_brand=accepted_inactive)
    response = api_client.get(url_depot(depot.pk))
    assert response.status_code == 200
    offers = response.json()["offers"]
    ids = {entry["id"] for entry in offers}
    assert str(visible_offer.pk) in ids
    assert str(inactive_offer.pk) not in ids
    assert str(hidden_unpublished_offer.pk) not in ids
    assert str(hidden_brand_offer.pk) not in ids
    serialized = next(entry for entry in offers if entry["id"] == str(visible_offer.pk))
    assert len(serialized["operations"]) == 1
    assert serialized["operations"][0]["operation_type"] == OperationType.REFILL
    assert str(accepted_live.pk) in {entry["id"] for entry in serialized["exchange_brands"]}
    assert str(accepted_inactive.pk) not in {entry["id"] for entry in serialized["exchange_brands"]}



@pytest.mark.django_db
@pytest.mark.parametrize("status", [DepotStatus.PENDING, DepotStatus.SUSPENDED, DepotStatus.DISABLED])
def test_non_active_depot_returns_unified_404(api_client, status):
    depot = make_depot(status=status, lat=AKWA[0], lng=AKWA[1])
    response = api_client.get(url_depot(depot.pk))
    assert_unified_error(response, status=404)
    assert set(response.json()) == ERROR_KEYS



@pytest.mark.django_db
@pytest.mark.parametrize("depot_id", ["not-an-uuid", "00000000-0000-0000-0000-000000000000"])
def test_unknown_or_malformed_uuid_returns_unified_404(api_client, depot_id):
    response = api_client.get(url_depot(depot_id))
    assert_unified_error(response, status=404)
    assert set(response.json()) == ERROR_KEYS



@pytest.mark.django_db
def test_detail_ignores_invalid_bearer(api_client):
    depot = make_depot(status=DepotStatus.ACTIVE, lat=AKWA[0], lng=AKWA[1])
    response = api_client.get(url_depot(depot.pk), HTTP_AUTHORIZATION="Bearer malformed.expired.token")
    assert response.status_code == 200



@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.django_db
def test_detail_write_methods_are_405_unified(api_client, method):
    depot = make_depot(status=DepotStatus.ACTIVE, lat=AKWA[0], lng=AKWA[1])
    response = getattr(api_client, method)(url_depot(depot.pk), data={}, format="json")
    assert_unified_error(response, status=405)
    assert set(response.json()) == ERROR_KEYS
