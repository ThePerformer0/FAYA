import pytest
from django.db import IntegrityError, transaction


from apps.catalog.models import Product
from apps.depots.models import Depot, DepotProductOffer, OfferOperation, OperationType, OfferExchangeBrand
from tests.factories_catalog import make_product, make_brand
from tests.factories_depots import make_depot, make_offer, make_operation, make_exchange_brand

pytestmark = pytest.mark.integration



@pytest.mark.django_db
class TestDepotDatabaseConstraints:
    def test_unique_offer_per_depot_and_product(self):
        depot = make_depot()
        product = make_product()
        offer = make_offer(depot=depot, product=product)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                DepotProductOffer.objects.create(depot=depot, product=product, is_active=True)

    def test_product_is_protected_from_deletion_when_offer_references_it(self):
        product = make_product()
        make_offer(depot=make_depot(), product=product)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                product.delete()

    def test_depot_deletion_cascades_to_offers(self):
        depot = make_depot()
        offer = make_offer(depot=depot, product=make_product())
        offer_id = offer.pk
        depot.delete()
        assert not DepotProductOffer.objects.filter(pk=offer_id).exists()



@pytest.mark.django_db
class TestOfferOperationDatabaseConstraints:
    def test_unique_operation_type_per_offer(self):
        offer = make_offer(depot=make_depot(), product=make_product())
        make_operation(offer, operation_type=OperationType.REFILL)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                OfferOperation.objects.create(offer=offer, operation_type=OperationType.REFILL, gas_price=1000)

    @pytest.mark.parametrize("operation_type", [OperationType.REFILL, OperationType.EXCHANGE])
    def test_sql_constraint_rejects_nonzero_bottle_or_deposit_cost_outside_first_acquisition(self, operation_type):
        offer = make_offer(depot=make_depot(), product=make_product())
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                OfferOperation.objects.create(
                    offer=offer, operation_type=operation_type, gas_price=1000,
                    bottle_price=1, deposit_amount=0,
                )



@pytest.mark.django_db
class TestOfferExchangeBrandDatabaseConstraints:
    def test_unique_accepted_brand_per_offer(self):
        offer = make_offer(depot=make_depot(), product=make_product())
        brand = make_brand(name="Exchange Brand")
        make_exchange_brand(offer, accepted_brand=brand)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                OfferExchangeBrand.objects.create(offer=offer, accepted_brand=brand)

    def test_accepted_brand_is_protected_from_deletion(self):
        offer = make_offer(depot=make_depot(), product=make_product())
        brand = make_brand(name="Protected Exchange Brand")
        make_exchange_brand(offer, accepted_brand=brand)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                brand.delete()
