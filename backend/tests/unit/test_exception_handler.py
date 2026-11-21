"""Handler d'exceptions DRF global : tout doit sortir en {code, message, details}.

Utilise des vues factices (tests/support_urls.py) branchées sur la vraie pile
middleware/DRF du projet.
"""
import inspect
import json

import pytest
from rest_framework.test import APIClient

from apps.core.exceptions import ConflictDomainError
from tests.helpers import assert_unified_error

pytestmark = [
    pytest.mark.unit,
    pytest.mark.django_db,
    pytest.mark.urls("tests.support_urls"),
]


@pytest.fixture
def client(settings):
    settings.DEBUG = False
    settings.DEBUG_PROPAGATE_EXCEPTIONS = False
    c = APIClient()
    c.raise_request_exception = False
    return c


def raise_url(kind):
    return f"/_t/raise/{kind}/"


# --------------------------------------------------------------------------
# Exceptions métier
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "name,status",
    [
        ("validation", 400),
        ("authentication", 401),
        ("forbidden", 403),
        ("notfound", 404),
        ("conflict", 409),
    ],
)
def test_domain_error_status_and_unified_format(client, name, status):
    response = client.get(raise_url(f"domain-{name}"))
    assert_unified_error(response, status)


def test_base_domain_error_is_an_error_status_with_unified_format(client):
    response = client.get(raise_url("domain-base"))
    assert 400 <= response.status_code < 600
    assert_unified_error(response)


def test_domain_error_custom_code_message_details_are_echoed(client):
    params = set(inspect.signature(ConflictDomainError.__init__).parameters)
    if not {"message", "code", "details"} <= params:
        pytest.skip("Le constructeur de DomainError n'accepte pas message/code/details")
    body = assert_unified_error(client.get(raise_url("domain-conflict")), 409)
    assert body["code"] == "test_code"
    assert body["message"] == "Message de test"
    assert body["details"] == {"champ": "valeur"}


# --------------------------------------------------------------------------
# Exceptions DRF / Django natives : jamais le format {"detail": ...}
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kind,status",
    [
        ("drf-validation", 400),
        ("drf-validation-list", 400),
        ("drf-not-authenticated", 401),
        ("drf-permission-denied", 403),
        ("drf-not-found", 404),
        ("drf-throttled", 429),
        ("drf-api-exception", 500),
        ("http404", 404),
        ("django-permission-denied", 403),
    ],
)
def test_native_exceptions_use_unified_format(client, kind, status):
    response = client.get(raise_url(kind))
    body = assert_unified_error(response, status)
    assert "detail" not in body


def test_drf_validation_error_keeps_field_information(client):
    body = assert_unified_error(client.get(raise_url("drf-validation")), 400)
    assert "email" in json.dumps(body["details"])


# --------------------------------------------------------------------------
# Requêtes mal formées
# --------------------------------------------------------------------------
def test_malformed_json_returns_400_unified(client):
    response = client.post("/_t/parse/", data="{pas du json", content_type="application/json")
    assert_unified_error(response, 400)


def test_unsupported_media_type_returns_415_unified(client):
    response = client.post("/_t/parse/", data="a=1", content_type="text/plain")
    assert_unified_error(response, 415)


def test_method_not_allowed_returns_405_unified(client):
    response = client.post("/_t/only-get/", data={}, format="json")
    assert_unified_error(response, 405)


def test_unknown_route_returns_404_unified(client):
    """Durcissement : une URL inexistante (hors DRF) doit aussi être en JSON unifié."""
    response = client.get("/api/v1/cette-route-n-existe-pas/")
    assert_unified_error(response, 404)


# --------------------------------------------------------------------------
# Authentification : 401 (et non 403) pour un anonyme
# --------------------------------------------------------------------------
def test_anonymous_on_protected_view_returns_401_not_403(client):
    response = client.get("/_t/protected/")
    assert_unified_error(response, 401)


def test_garbage_bearer_returns_401_unified(client):
    client.credentials(HTTP_AUTHORIZATION="Bearer ceci.n.est.pas.un.jwt")
    response = client.get("/_t/protected/")
    assert_unified_error(response, 401)


# --------------------------------------------------------------------------
# Erreur non gérée : 500 générique, aucune fuite
# --------------------------------------------------------------------------
def test_unhandled_exception_returns_generic_500_without_leak(client):
    response = client.get(raise_url("unhandled"))
    assert_unified_error(response, 500)
    text = response.content.decode().lower()
    for leaked in ("hunter2", "accounts_user", "traceback", "runtimeerror", "secret interne"):
        assert leaked not in text, f"fuite d'information dans la réponse 500: {leaked!r}"
