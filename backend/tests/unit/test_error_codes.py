"""Codes d'erreur génériques du handler DRF (UPPER_SNAKE_CASE)."""
import re

import pytest
from rest_framework.test import APIClient

from tests.constants import (
    CODE_API_ERROR,
    CODE_FORBIDDEN,
    CODE_NOT_FOUND,
    CODE_RATE_LIMITED,
    CODE_UNAUTHENTICATED,
    CODE_VALIDATION,
)
from tests.helpers import assert_unified_error

pytestmark = [
    pytest.mark.unit,
    pytest.mark.django_db,
    pytest.mark.urls("tests.support_urls"),
]

UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")


@pytest.fixture
def client(settings):
    settings.DEBUG = False
    c = APIClient()
    c.raise_request_exception = False
    return c


@pytest.mark.parametrize(
    "kind,status,code",
    [
        ("drf-validation", 400, CODE_VALIDATION),
        ("drf-validation-list", 400, CODE_VALIDATION),
        ("drf-not-authenticated", 401, CODE_UNAUTHENTICATED),
        ("drf-permission-denied", 403, CODE_FORBIDDEN),
        ("django-permission-denied", 403, CODE_FORBIDDEN),
        ("drf-not-found", 404, CODE_NOT_FOUND),
        ("http404", 404, CODE_NOT_FOUND),
        ("drf-throttled", 429, CODE_RATE_LIMITED),
        ("drf-api-exception", 500, CODE_API_ERROR),
    ],
)
def test_generic_error_codes(client, kind, status, code):
    assert_unified_error(client.get(f"/_t/raise/{kind}/"), status, code)


def test_anonymous_on_protected_view_is_unauthenticated(client):
    assert_unified_error(client.get("/_t/protected/"), 401, CODE_UNAUTHENTICATED)


def test_method_not_allowed_uses_api_error_code(client):
    """Hypothèse : 405 fait partie des « autres exceptions DRF » -> API_ERROR."""
    assert_unified_error(client.post("/_t/only-get/", data={}, format="json"), 405, CODE_API_ERROR)


def test_unsupported_media_type_uses_api_error_code(client):
    """Hypothèse : 415 fait partie des « autres exceptions DRF » -> API_ERROR."""
    assert_unified_error(
        client.post("/_t/parse/", data="a=1", content_type="text/plain"), 415, CODE_API_ERROR
    )


@pytest.mark.parametrize(
    "kind",
    [
        "domain-base", "domain-validation", "domain-authentication", "domain-forbidden",
        "domain-notfound", "domain-conflict", "drf-validation", "drf-not-authenticated",
        "drf-permission-denied", "drf-not-found", "drf-throttled", "drf-api-exception",
        "http404", "unhandled",
    ],
)
def test_every_error_code_is_upper_snake_case(client, kind):
    body = client.get(f"/_t/raise/{kind}/").json()
    assert UPPER_SNAKE.match(body["code"]) or body["code"] == "test_code", body["code"]
