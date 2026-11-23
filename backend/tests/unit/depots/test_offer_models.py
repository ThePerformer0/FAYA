import pytest
from django.core.exceptions import ValidationError


from apps.catalog.models import Product, ProductStatus, ProductType
from apps.depots.models import DepotProductOffer, OfferOperation, OperationType, OfferExchangeBrand
from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import make_depot, make_offer, make_operation, make_exchange_brand

pytestmark = pytest.mark.unit



@pytest.mark.django_db
class TestDepotProductOfferModel:
    def test_offer_factory_links_depot_and_product(self):
        offer = make_offer(depot=make_depot(), product=make_product())
        assert offer.depot_id is not None
        assert offer.product_id is not None

    def test_offer_is_active_by_default(self):
        offer = make_offer(depot=make_depot(), product=make_product())
        assert offer.is_active is True



@pytest.mark.django_db
class TestOfferOperationModel:
    @pytest.mark.parametrize("operation_type", [OperationType.REFILL, OperationType.EXCHANGE])
    def test_non_first_acquisition_requires_zero_bottle_and_deposit_amounts(self, operation_type):
        offer = make_offer(depot=make_depot(), product=make_product())
        operation = OfferOperation(
            offer=offer, operation_type=operation_type, gas_price=1000,
            bottle_price=100, deposit_amount=500,
        )
        with pytest.raises(ValidationError):
            operation.clean()

    def test_first_acquisition_accepts_bottle_and_deposit_prices(self):
        offer = make_offer(depot=make_depot(), product=make_product())
        operation = make_operation(
            offer, operation_type=OperationType.FIRST_ACQUISITION,
            gas_price=1000, bottle_price=5000, deposit_amount=1000,
        )
        operation.full_clean()
        assert operation.total_unit_price == 7000

    @pytest.mark.parametrize("operation_type", [OperationType.REFILL, OperationType.EXCHANGE])
    def test_total_unit_price_for_other_operations_is_gas_price(self, operation_type):
        offer = make_offer(depot=make_depot(), product=make_product())
        operation = make_operation(offer, operation_type=operation_type, gas_price=1750)
        assert operation.total_unit_price == 1750



@pytest.mark.django_db
class TestOfferExchangeBrandModel:
    def test_exchange_brand_factory_creates_relation(self):
        offer = make_offer(depot=make_depot(), product=make_product())
        accepted_brand = make_brand(name="Accepted Brand")
        exchange = make_exchange_brand(offer, accepted_brand=accepted_brand)
        assert exchange.offer_id == offer.pk
        assert exchange.accepted_brand_id == accepted_brand.pk



    def test_clean_rejects_product_brand_as_accepted_exchange_brand(self):
        product = make_product()
        offer = make_offer(depot=make_depot(), product=product)
        exchange = OfferExchangeBrand(offer=offer, accepted_brand=product.brand)
        with pytest.raises(ValidationError):
            exchange.clean()
