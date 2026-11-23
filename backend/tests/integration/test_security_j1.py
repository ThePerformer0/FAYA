"""Black-box security regression tests for the public Jalon 1 API."""

import pytest

from tests.constants import ERROR_KEYS
from tests.constants_j1 import URL_PUBLIC_SETTINGS, URL_BRANDS, URL_PRODUCTS, URL_DEPOTS, url_depot
from tests.factories_catalog import make_brand, make_product
from tests.factories_depots import make_depot
from tests.helpers import assert_unified_error

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

INJECTION_VALUES = [
    "' OR 1=1 --", '"; DROP TABLE depots; --', "%", "_", "\\", "\x00",
]


def _assert_json(response):
    assert response["Content-Type"].startswith("application/json")


def _assert_no_internal_fields(payload):
    forbidden = {"manager", "manager_id", "email", "password", "status", "is_active"}
    if isinstance(payload, dict):
        assert not (forbidden & payload.keys()), f"Internal fields leaked: {forbidden & payload.keys()}"
        for value in payload.values():
            _assert_no_internal_fields(value)
    elif isinstance(payload, list):
        for value in payload:
            _assert_no_internal_fields(value)


@pytest.mark.parametrize("value", INJECTION_VALUES)
def test_depot_search_payloads_never_cause_server_error(api_client, value):
    response = api_client.get(URL_DEPOTS, {"q": value}, format="json")
    assert response.status_code != 500
    _assert_json(response)
    if response.status_code == 400:
        assert set(response.data) == set(ERROR_KEYS)


@pytest.mark.parametrize("param", ["brand", "capacity_kg", "operation", "open_now", "lat", "lng", "radius_km"])
@pytest.mark.parametrize("value", INJECTION_VALUES)
def test_depot_filter_payloads_never_cause_server_error(api_client, param, value):
    response = api_client.get(URL_DEPOTS, {param: value}, format="json")
    assert response.status_code != 500
    _assert_json(response)
    if response.status_code == 400:
        assert set(response.data) == set(ERROR_KEYS)


def test_all_public_endpoints_ignore_invalid_bearer_and_return_json(api_client):
    depot = make_depot()
    endpoints = [URL_PUBLIC_SETTINGS, URL_BRANDS, URL_PRODUCTS, URL_DEPOTS, url_depot(depot.pk)]
    browser_accept = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    for url in endpoints:
        response = api_client.get(
            url,
            HTTP_AUTHORIZATION="Bearer definitely.invalid.token",
            HTTP_ACCEPT=browser_accept,
        )
        assert response.status_code == 200, (url, response.content)
        _assert_json(response)

        strict_html = api_client.get(
            url,
            HTTP_AUTHORIZATION="Bearer definitely.invalid.token",
            HTTP_ACCEPT="text/html",
        )
        assert_unified_error(strict_html, status=406)
        _assert_json(strict_html)


def test_public_responses_do_not_leak_internal_model_fields(api_client):
    brand = make_brand(name="Public safe brand")
    make_product(brand=brand, capacity_kg="12.50")
    depot = make_depot()
    for url in (URL_BRANDS, URL_PRODUCTS, URL_DEPOTS, url_depot(depot.pk)):
        response = api_client.get(url, format="json")
        assert response.status_code == 200
        _assert_no_internal_fields(response.data)


def test_time_dependent_endpoints_do_not_advertise_public_cache(api_client):
    depot = make_depot()
    for url in (URL_PUBLIC_SETTINGS, URL_DEPOTS, url_depot(depot.pk)):
        response = api_client.get(url, format="json")
        assert response.status_code == 200
        cache_control = response.get("Cache-Control", "").lower()
        assert "public" not in cache_control
        assert "max-age" not in cache_control


@pytest.mark.parametrize("url", [URL_PUBLIC_SETTINGS, URL_BRANDS, URL_PRODUCTS, URL_DEPOTS])
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_public_read_only_endpoints_reject_write_methods_unified(api_client, url, method):
    response = getattr(api_client, method)(url, {}, format="json")
    assert_unified_error(response, status=405)
    _assert_json(response)


def test_depot_detail_rejects_write_methods_unified(api_client):
    depot = make_depot()
    for method in ("post", "put", "patch", "delete"):
        response = getattr(api_client, method)(url_depot(depot.pk), {}, format="json")
        assert_unified_error(response, status=405)
        _assert_json(response)

@pytest.mark.parametrize("param", ["brand", "capacity_kg", "product_type"])
@pytest.mark.parametrize("value", INJECTION_VALUES)
def test_catalog_product_filters_never_cause_server_error(api_client, param, value):
    response = api_client.get(URL_PRODUCTS, {param: value}, format="json")
    assert response.status_code != 500
    _assert_json(response)
    if response.status_code == 400:
        assert set(response.data) == set(ERROR_KEYS)


@pytest.mark.parametrize("value", INJECTION_VALUES)
def test_catalog_brand_uuid_filter_never_causes_server_error(api_client, value):
    response = api_client.get(URL_PRODUCTS, {"brand": value}, format="json")
    assert response.status_code != 500
    _assert_json(response)
    if response.status_code == 400:
        assert set(response.data) == set(ERROR_KEYS)
