import pytest
from decimal import Decimal

from apps.catalog.models import ProductStatus
from apps.depots.models import DepotStatus
from apps.depots.selectors import search_public_depots
from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import make_depot, make_offer, make_operation
from tests.geo import point, equator_point, haversine_m, DOUALA_CENTER

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _depot_with_published_offer(name, lat, lng):
    depot = make_depot(name=name, status=DepotStatus.ACTIVE, lat=lat, lng=lng)
    brand = make_brand(name=f"{name} brand")
    product = make_product(brand=brand, capacity_kg=Decimal("12.5"), status=ProductStatus.PUBLISHED)
    offer = make_offer(depot, product, is_active=True)
    make_operation(offer, is_active=True)
    return depot



def test_postgis_distance_annotation_matches_haversine_within_tolerance():
    origin_lat, origin_lng = 0.0, 0.0
    target = equator_point(1250.0)
    depot = _depot_with_published_offer("1250m target", target.y, target.x)
    results = search_public_depots(lat=origin_lat, lng=origin_lng, radius_km=2.0)
    found = next(d for d in results if d.pk == depot.pk)
    expected = haversine_m(origin_lat, origin_lng, target.y, target.x)
    assert abs(float(found.distance_geo.m) - expected) <= 2.0


@pytest.mark.parametrize("radius_km, distance_m, should_match", [
    (Decimal("0.1"), 99.0, True),
    (Decimal("0.1"), 101.0, False),
    (Decimal("200.0"), 199_999.0, True),
    (Decimal("200.0"), 200_001.0, False),
])
def test_radius_limits_are_applied_at_geographic_distance_boundary(radius_km, distance_m, should_match):
    target = equator_point(distance_m)
    depot = make_depot(name=f"Boundary {radius_km} {distance_m}", status=DepotStatus.ACTIVE, lat=target.y, lng=target.x)
    results = search_public_depots(lat=0.0, lng=0.0, radius_km=radius_km)
    assert (depot.pk in {d.pk for d in results}) is should_match


def test_radius_filter_uses_geography_distance_not_degree_approximation():
    inside = equator_point(999.0)
    outside = equator_point(1001.0)
    d_inside = _depot_with_published_offer("Inside 1km", inside.y, inside.x)
    d_outside = _depot_with_published_offer("Outside 1km", outside.y, outside.x)
    results = search_public_depots(lat=0.0, lng=0.0, radius_km=1.0)
    ids = {d.pk for d in results}
    assert d_inside.pk in ids
    assert d_outside.pk not in ids


def test_douala_distance_ordering_matches_haversine_reference():
    origin_lat, origin_lng = DOUALA_CENTER
    far_equator_pt = equator_point(2500.0, origin_lng=origin_lng)
    far_pt = point(origin_lat, far_equator_pt.x)
    close = make_depot(name="Near Douala", status=DepotStatus.ACTIVE, lat=origin_lat, lng=origin_lng)
    far = make_depot(name="Far Douala", status=DepotStatus.ACTIVE, lat=far_pt.y, lng=far_pt.x)
    results = list(search_public_depots(lat=origin_lat, lng=origin_lng))
    ids = [d.pk for d in results]
    assert ids.index(close.pk) < ids.index(far.pk)
    expected = haversine_m(origin_lat, origin_lng, far_pt.y, far_pt.x)
    far_result = next(d for d in results if d.pk == far.pk)
    assert abs(float(far_result.distance_geo.m) - expected) <= 5.0
