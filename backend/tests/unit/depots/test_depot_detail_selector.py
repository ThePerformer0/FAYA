import uuid
import pytest

from apps.depots.models import DepotStatus, OperationType
from apps.catalog.models import ProductStatus
from apps.depots.selectors import get_public_depot_detail
from apps.core.exceptions import NotFoundDomainError
from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import make_depot, make_offer, make_operation, make_exchange_brand

pytestmark = pytest.mark.unit


@pytest.mark.django_db
class TestGetPublicDepotDetail:
    def test_returns_active_depot_with_public_related_data(self):
        depot = make_depot(name="Detail depot", status=DepotStatus.ACTIVE)
        brand = make_brand(name="Published brand", is_active=True)
        product = make_product(brand=brand, status=ProductStatus.PUBLISHED)
        offer = make_offer(depot, product, is_active=True)
        make_operation(offer, operation_type=OperationType.REFILL, is_active=True)
        accepted_brand = make_brand(name="Accepted brand", is_active=True)
        make_exchange_brand(offer, accepted_brand)
        detail = get_public_depot_detail(depot_id=depot.pk)
        assert detail.pk == depot.pk
        assert detail.offers.filter(pk=offer.pk).exists()
        assert offer.operations.filter(is_active=True).exists()
        assert offer.exchange_brands.filter(accepted_brand__is_active=True).exists()

    @pytest.mark.parametrize("status", [DepotStatus.PENDING, DepotStatus.SUSPENDED, DepotStatus.DISABLED])
    def test_non_active_depot_is_not_public(self, status):
        depot = make_depot(name=f"Hidden {status}", status=status)
        with pytest.raises(NotFoundDomainError):
            get_public_depot_detail(depot_id=depot.pk)

    def test_unknown_uuid_raises_not_found_domain_error(self):
        with pytest.raises(NotFoundDomainError):
            get_public_depot_detail(depot_id=uuid.uuid4())
