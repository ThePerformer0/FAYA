"""Black-box integration tests for the public catalog API (Jalon 1, Lot 3)."""
from decimal import Decimal

from django.urls import reverse
import pytest

from apps.catalog.models import Brand, Product, ProductStatus, ProductType
from apps.accounts.models import UserRole
from tests.factories_catalog import make_brand, make_product
from tests.helpers import assert_unified_error, create_user
from tests.constants import ERROR_KEYS
from tests.constants_j1 import URL_BRANDS, URL_PRODUCTS


pytestmark = pytest.mark.integration


def _product_payload(item):
    assert set(item) == {
        "id", "brand", "capacity_kg", "product_type", "name", "description", "characteristics", "image_url"
    }
    assert set(item["brand"]) == {"id", "name", "logo_url"}
    assert isinstance(item["capacity_kg"], str)



@pytest.mark.django_db
def test_brands_endpoint_returns_unpaginated_active_brands_only(api_client):
    active = make_brand(name="Visible Brand", is_active=True)
    make_brand(name="Hidden Brand", is_active=False)


    response = api_client.get(URL_BRANDS)


    assert response.status_code == 200
    assert isinstance(response.data, list)
    assert len(response.data) == 1
    assert set(response.data[0]) == {"id", "name", "logo_url"}
    assert response.data[0]["id"] == str(active.pk)
    assert response.data[0]["name"] == active.name
    assert response.data[0]["logo_url"] == active.logo_url



@pytest.mark.django_db
def test_brands_endpoint_is_not_paginated_and_ignores_page_parameters(api_client):
    for i in range(25):
        make_brand(name=f"Brand {i:02d}")
    response = api_client.get(URL_BRANDS, {"page": 2, "page_size": 1})
    assert response.status_code == 200
    assert isinstance(response.data, list)
    assert len(response.data) == 25



@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.django_db
def test_brands_endpoint_rejects_write_methods_with_unified_405(api_client, method):
    response = getattr(api_client, method)(URL_BRANDS, data={}, format="json")
    assert_unified_error(response, status=405)
    assert set(response.data) == ERROR_KEYS



@pytest.mark.django_db
def test_products_endpoint_only_returns_published_products_of_active_brands(api_client):
    active_brand = make_brand(name="Active Products Brand", is_active=True)
    inactive_brand = make_brand(name="Inactive Products Brand", is_active=False)
    make_product(brand=active_brand, capacity_kg=Decimal("12.5"), status=ProductStatus.PUBLISHED)
    make_product(brand=active_brand, capacity_kg=Decimal("6.0"), status=ProductStatus.DRAFT)
    make_product(brand=active_brand, capacity_kg=Decimal("35.0"), status=ProductStatus.ARCHIVED)
    make_product(brand=inactive_brand, capacity_kg=Decimal("12.5"), status=ProductStatus.PUBLISHED)


    response = api_client.get(URL_PRODUCTS)


    assert response.status_code == 200
    assert response.data["count"] == 1
    assert len(response.data["results"]) == 1
    _product_payload(response.data["results"][0])



@pytest.mark.django_db
def test_products_response_uses_standard_pagination_shape(api_client):
    brand = make_brand(name="Pagination Products")
    for i in range(23):
        make_product(
            brand=brand,
            capacity_kg=Decimal(i + 1),
            status=ProductStatus.PUBLISHED,
            name=f"Product {i:02d}",
        )

    response = api_client.get(URL_PRODUCTS)

    assert response.status_code == 200
    assert set(response.data) == {"count", "next", "previous", "results"}
    assert response.data["count"] == 23
    assert len(response.data["results"]) == 20
    assert response.data["next"] is not None
    assert response.data["previous"] is None



@pytest.mark.django_db
def test_products_page_size_is_capped_at_50(api_client):
    brand = make_brand(name="Page Size Cap")
    for i in range(55):
        make_product(
            brand=brand,
            capacity_kg=Decimal(i + 1),
            status=ProductStatus.PUBLISHED,
            name=f"Cap {i:02d}",
        )

    response = api_client.get(URL_PRODUCTS, {"page_size": 100})

    assert response.status_code == 200
    assert len(response.data["results"]) == 50



@pytest.mark.django_db
def test_products_invalid_page_returns_unified_404(api_client):
    brand = make_brand(name="Invalid Page")
    make_product(brand=brand, status=ProductStatus.PUBLISHED)
    response = api_client.get(URL_PRODUCTS, {"page": 999})
    assert_unified_error(response, status=404)
    assert set(response.data) == ERROR_KEYS



@pytest.mark.parametrize("query_value", ["not-a-uuid", "", " "])
@pytest.mark.django_db
def test_invalid_brand_filter_returns_unified_400(api_client, query_value):
    response = api_client.get(URL_PRODUCTS, {"brand": query_value})
    assert_unified_error(response, status=400)
    assert set(response.data) == ERROR_KEYS



@pytest.mark.parametrize("capacity", ["0", "0.001", "-1", "123456.78", "12.345", "abc", ""])
@pytest.mark.django_db
def test_invalid_capacity_filter_returns_unified_400(api_client, capacity):
    response = api_client.get(URL_PRODUCTS, {"capacity_kg": capacity})
    assert_unified_error(response, status=400)
    assert set(response.data) == ERROR_KEYS



@pytest.mark.parametrize("product_type", ["UNKNOWN", "butane", "", " ", "NATURAL_GAS"])
@pytest.mark.django_db
def test_invalid_product_type_filter_returns_unified_400(api_client, product_type):
    response = api_client.get(URL_PRODUCTS, {"product_type": product_type})
    assert_unified_error(response, status=400)
    assert set(response.data) == ERROR_KEYS



@pytest.mark.django_db
def test_products_brand_capacity_and_type_filters_are_applied(api_client):
    brand_a = make_brand(name="Filter Brand A")
    brand_b = make_brand(name="Filter Brand B")
    matching = make_product(brand=brand_a, capacity_kg=Decimal("12.5"), product_type=ProductType.BUTANE)
    make_product(brand=brand_a, capacity_kg=Decimal("6.0"), product_type=ProductType.BUTANE)
    make_product(brand=brand_a, capacity_kg=Decimal("12.5"), product_type=ProductType.PROPANE)
    make_product(brand=brand_b, capacity_kg=Decimal("12.5"), product_type=ProductType.BUTANE)

    response = api_client.get(URL_PRODUCTS, {
        "brand": str(brand_a.pk), "capacity_kg": "12.50", "product_type": "BUTANE"
    })

    assert response.status_code == 200
    assert response.data["count"] == 1
    result = response.data["results"][0]
    _product_payload(result)
    assert result["id"] == str(matching.pk)
    assert result["capacity_kg"] == "12.50"
    assert result["product_type"] == "BUTANE"
    assert result["brand"]["id"] == str(brand_a.pk)



@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.django_db
def test_products_endpoint_rejects_write_methods_with_unified_405(api_client, method):
    response = getattr(api_client, method)(URL_PRODUCTS, data={}, format="json")
    assert_unified_error(response, status=405)
    assert set(response.data) == ERROR_KEYS



@pytest.mark.django_db
def test_public_catalog_ignores_invalid_expired_or_corrupted_bearer(api_client):
    make_brand(name="Public Without Auth")
    make_product(status=ProductStatus.PUBLISHED)
    for token in ["expired.token.value", "not-a-token", "Bearer???"]:
        response = api_client.get(URL_PRODUCTS, HTTP_AUTHORIZATION=f"Bearer {token}")
        assert response.status_code == 200
