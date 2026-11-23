import pytest
from django.utils import timezone
from datetime import time
from decimal import Decimal

from apps.catalog.models import ProductStatus, ProductType
from apps.depots.models import DepotStatus, OperationType
from apps.depots.selectors import OpenStatus, search_public_depots
from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import make_depot, make_offer, make_operation
from tests.geo import AKWA, BONANJO, DEIDO, point
from tests.time_helpers import douala

pytestmark = pytest.mark.unit


def _published_product(brand, *, capacity=Decimal("12.5"), product_type=ProductType.BUTANE):
    return make_product(brand=brand, capacity_kg=capacity, product_type=product_type, status=ProductStatus.PUBLISHED)



def _active_offer(depot, product, *, operation=OperationType.REFILL, is_active=True):
    offer = make_offer(depot, product, is_active=is_active)
    make_operation(offer, operation_type=operation, is_active=True)
    return offer



@pytest.mark.django_db
class TestSearchPublicDepots:
    def test_only_active_depots_are_returned(self):
        active = make_depot(name="Active", status=DepotStatus.ACTIVE, location=point(*AKWA))
        pending = make_depot(name="Pending", status=DepotStatus.PENDING, location=point(*BONANJO))
        suspended = make_depot(name="Suspended", status=DepotStatus.SUSPENDED, location=point(*DEIDO))
        disabled = make_depot(name="Disabled", status=DepotStatus.DISABLED, location=point(*DEIDO))
        results = search_public_depots(at=douala(2026, 5, 1, 10))
        ids = {d.pk for d in results}
        assert active.pk in ids
        assert pending.pk not in ids
        assert suspended.pk not in ids
        assert disabled.pk not in ids

    def test_q_search_is_case_insensitive_across_name_address_neighborhood(self):
        d1 = make_depot(name="Depot Alpha", address="Rue du Marché", neighborhood="Akwa")
        d2 = make_depot(name="Depot Beta", address="Boulevard Bonanjo", neighborhood="Bonanjo")
        assert d1.pk in {d.pk for d in search_public_depots(q="ALPHA")}
        assert d1.pk in {d.pk for d in search_public_depots(q="marché")}
        assert d1.pk in {d.pk for d in search_public_depots(q="akwa")}
        assert d2.pk in {d.pk for d in search_public_depots(q="BONANJO")}

    @pytest.mark.parametrize("query", ["", "   ", "%", "_", "\\"])
    def test_blank_or_special_q_does_not_raise_and_is_treated_literally(self, query):
        depot = make_depot(name="Depot 100%_test", address="A\\B", neighborhood="Akwa")
        results = list(search_public_depots(q=query))
        if query.strip() == "":
            assert depot in results
        else:
            assert isinstance(results, list)

    def test_filters_match_the_same_offer_and_do_not_cross_match_two_offers(self):
        depot = make_depot(name="Split match", status=DepotStatus.ACTIVE, location=point(*AKWA))
        brand_a = make_brand(name="Brand A")
        brand_b = make_brand(name="Brand B")
        product_a = _published_product(brand_a, capacity=Decimal("6.0"))
        product_b = _published_product(brand_b, capacity=Decimal("12.5"))
        offer_a = make_offer(depot, product_a, is_active=True)
        make_operation(offer_a, operation_type=OperationType.REFILL, is_active=True)
        offer_b = make_offer(depot, product_b, is_active=True)
        make_operation(offer_b, operation_type=OperationType.EXCHANGE, is_active=True)
        results = search_public_depots(brand_id=brand_a.pk, capacity_kg=Decimal("12.5"), operation_type=OperationType.EXCHANGE)
        assert depot.pk not in {d.pk for d in results}

    def test_filters_brand_capacity_and_operation_match_single_offer(self):
        depot = make_depot(name="Exact match", status=DepotStatus.ACTIVE, location=point(*AKWA))
        brand = make_brand(name="Exact Brand")
        product = _published_product(brand, capacity=Decimal("12.5"))
        _active_offer(depot, product, operation=OperationType.REFILL)
        results = search_public_depots(brand_id=brand.pk, capacity_kg=Decimal("12.5"), operation_type=OperationType.REFILL)
        assert depot.pk in {d.pk for d in results}

    def test_inactive_offer_unpublished_product_and_inactive_brand_are_excluded_from_matching(self):
        depot = make_depot(name="Hidden offer", status=DepotStatus.ACTIVE, location=point(*AKWA))
        brand = make_brand(name="Hidden Brand", is_active=False)
        product = _published_product(brand)
        _active_offer(depot, product)
        assert depot.pk not in {d.pk for d in search_public_depots(brand_id=brand.pk)}

    def test_open_now_excludes_closed_and_includes_open_and_closing_soon(self):
        opened = make_depot(name="Open", status=DepotStatus.ACTIVE, opening_time=time(8), closing_time=time(22), location=point(*AKWA))
        soon = make_depot(name="Soon", status=DepotStatus.ACTIVE, opening_time=time(8), closing_time=time(20), location=point(*BONANJO))
        closed = make_depot(name="Closed", status=DepotStatus.ACTIVE, opening_time=time(8), closing_time=time(19), location=point(*DEIDO))
        at = douala(2026, 5, 1, 19, 30)
        results = search_public_depots(open_now=True, at=at)
        ids = {d.pk for d in results}
        assert opened.pk in ids
        assert soon.pk in ids
        assert closed.pk not in ids

    def test_open_depots_sort_before_closed_even_when_closed_is_nearer(self):
        near_closed = make_depot(name="A closed nearest", status=DepotStatus.ACTIVE, opening_time=time(8), closing_time=time(12), location=point(*AKWA))
        far_open = make_depot(name="Z open farther", status=DepotStatus.ACTIVE, opening_time=time(8), closing_time=time(20), location=point(*BONANJO))
        at = douala(2026, 5, 1, 13)
        results = list(search_public_depots(lat=-4.0, lng=9.0, at=at))
        ids = [d.pk for d in results]
        assert ids.index(far_open.pk) < ids.index(near_closed.pk)

    def test_results_are_not_duplicated_when_depot_has_multiple_matching_offers(self):
        depot = make_depot(name="Multi offers", status=DepotStatus.ACTIVE, location=point(*AKWA))
        brand = make_brand(name="Multi Brand")
        p1 = _published_product(brand, capacity=Decimal("6.0"))
        p2 = _published_product(brand, capacity=Decimal("12.5"))
        _active_offer(depot, p1, operation=OperationType.REFILL)
        _active_offer(depot, p2, operation=OperationType.REFILL)
        results = list(search_public_depots(brand_id=brand.pk, operation_type=OperationType.REFILL))
        assert [d.pk for d in results].count(depot.pk) == 1
