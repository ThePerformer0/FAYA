import pytest
from tests.constants import ERROR_KEYS
from tests.constants_j1 import URL_DEPOTS
from tests.helpers import assert_unified_error

pytestmark = pytest.mark.integration



@pytest.mark.django_db
@pytest.mark.parametrize("params", [
    {"lat": "0"}, {"lng": "0"}, {"radius_km": "1"},
    {"lat": "91", "lng": "0"}, {"lat": "-91", "lng": "0"},
    {"lat": "0", "lng": "181"}, {"lat": "0", "lng": "-181"},
    {"lat": "0", "lng": "0", "radius_km": "0.09"},
    {"lat": "0", "lng": "0", "radius_km": "200.01"},
    {"brand": ""}, {"lat": ""}, {"operation": ""}, {"capacity_kg": ""},
    {"q": "x" * 121}, {"brand": "not-a-uuid"}, {"operation": "INVALID"},
    {"open_now": "not-a-bool"},
])
def test_invalid_depot_list_query_parameters_return_unified_400(api_client, params):
    response = api_client.get(URL_DEPOTS, params)
    assert_unified_error(response, status=400)
    assert set(response.json()) == ERROR_KEYS
    assert response["Content-Type"].startswith("application/json")



@pytest.mark.django_db
@pytest.mark.parametrize("params", [
    {"lat": "90", "lng": "180"},
    {"lat": "-90", "lng": "-180"},
    {"lat": "0", "lng": "0", "radius_km": "0.1"},
    {"lat": "0", "lng": "0", "radius_km": "200.0"},
    {"q": ""},
])
def test_valid_boundary_values_are_accepted(api_client, params):
    response = api_client.get(URL_DEPOTS, params)
    assert response.status_code == 200



@pytest.mark.django_db
@pytest.mark.parametrize("params", [
    {"capacity_kg": "0"}, {"capacity_kg": "0.001"},
    {"capacity_kg": "123456.00"}, {"capacity_kg": "12.345"},
    {"capacity_kg": "abc"},
])
def test_invalid_capacity_filter_is_unified_400(api_client, params):
    response = api_client.get(URL_DEPOTS, params)
    assert_unified_error(response, status=400)
    assert set(response.json()) == ERROR_KEYS
