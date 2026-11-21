"""Fixtures partagées."""
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts.models import UserRole
from apps.core.models import PlatformSetting
from tests import helpers
from tests.constants import VALID_PASSWORD


@pytest.fixture(autouse=True)
def _clear_cache():
    """Évite que le throttling DRF / le cache fuite d'un test à l'autre."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def password():
    return VALID_PASSWORD


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def customer(db):
    return helpers.create_user(role=UserRole.CUSTOMER)


@pytest.fixture
def other_customer(db):
    return helpers.create_user(role=UserRole.CUSTOMER)


@pytest.fixture
def depot_manager(db):
    return helpers.create_user(role=UserRole.DEPOT_MANAGER)


@pytest.fixture
def admin_user(db):
    return helpers.create_user(role=UserRole.ADMIN, is_staff=True)


@pytest.fixture
def auth_client():
    """Fabrique un APIClient authentifié en Bearer pour un utilisateur donné."""

    def _make(user):
        from apps.accounts.services import issue_auth_tokens

        tokens = issue_auth_tokens(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens.access_token}")
        return client

    return _make


@pytest.fixture
def platform_setting(db):
    """Garantit l'existence du singleton PlatformSetting (id=1)."""
    obj, _ = PlatformSetting.objects.get_or_create(id=1)
    return obj
