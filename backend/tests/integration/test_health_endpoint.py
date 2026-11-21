"""GET /api/v1/health/ : public, vérifie API + PostgreSQL (200 ou 503).

C'est le seul endroit où la connexion DB est simulée en panne (on ne peut pas
couper PostgreSQL proprement depuis pytest).
"""
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.db.backends.base.base import BaseDatabaseWrapper
from rest_framework.test import APIClient

from tests.constants import URL_HEALTH
from tests.helpers import assert_unified_error

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

SENSITIVE_FRAGMENTS = [
    "db.internal.example",
    "10.0.0.5",
    "faya_secret_user",
    "password authentication",
    "traceback",
    "operationalerror",
]


@contextmanager
def database_down():
    error = OperationalError(
        'connection to server at "db.internal.example" (10.0.0.5), port 5432 failed: '
        'FATAL: password authentication failed for user "faya_secret_user"'
    )
    with ExitStack() as stack:
        stack.enter_context(patch.object(BaseDatabaseWrapper, "cursor", side_effect=error))
        stack.enter_context(
            patch.object(BaseDatabaseWrapper, "ensure_connection", side_effect=error)
        )
        yield


def test_health_is_ok_when_everything_works():
    response = APIClient().get(URL_HEALTH)
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_health_is_public_no_credentials_needed():
    client = APIClient()
    client.credentials()  # aucun header d'authentification
    assert client.get(URL_HEALTH).status_code == 200


def test_health_uses_few_queries(django_assert_max_num_queries):
    with django_assert_max_num_queries(2):
        assert APIClient().get(URL_HEALTH).status_code == 200


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_health_rejects_non_get_methods(method):
    response = getattr(APIClient(), method)(URL_HEALTH, data={}, format="json")
    assert_unified_error(response, 405)


def test_health_returns_503_when_database_is_down():
    client = APIClient()
    client.raise_request_exception = False
    with database_down():
        response = client.get(URL_HEALTH)
    assert response.status_code == 503


def test_health_503_does_not_leak_connection_details():
    client = APIClient()
    client.raise_request_exception = False
    with database_down():
        response = client.get(URL_HEALTH)
    text = response.content.decode().lower()
    for fragment in SENSITIVE_FRAGMENTS:
        assert fragment not in text, f"fuite dans le 503 : {fragment!r}"


def test_health_recovers_after_outage_no_sticky_state():
    client = APIClient()
    client.raise_request_exception = False
    with database_down():
        assert client.get(URL_HEALTH).status_code == 503
    assert client.get(URL_HEALTH).status_code == 200
