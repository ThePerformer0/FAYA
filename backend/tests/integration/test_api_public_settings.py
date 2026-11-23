"""GET /api/v1/settings/public/ (AllowAny)."""
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.utils.dateparse import parse_datetime
from freezegun import freeze_time
from rest_framework.test import APIClient
from rest_framework_simplejwt.settings import api_settings as jwt_settings

from apps.accounts import services
from apps.core.models import PlatformSetting
from tests.api_helpers import bearer
from tests.constants import ERROR_KEYS
from tests.constants_j1 import (
    PLATFORM_TIMEZONE,
    PUBLIC_SETTINGS_INT_KEYS,
    PUBLIC_SETTINGS_KEYS,
    URL_PUBLIC_SETTINGS,
)
from tests.helpers import assert_unified_error
from tests.time_helpers import douala

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def fetch(client=None):
    return (client or APIClient()).get(URL_PUBLIC_SETTINGS)


# ==========================================================================
# Contenu
# ==========================================================================
class TestPublicSettingsContent:
    def test_anonymous_gets_200_json(self):
        r = fetch()
        assert r.status_code == 200, r.content
        assert r["Content-Type"].startswith("application/json")

    def test_exact_documented_keys(self):
        assert set(fetch().json()) == PUBLIC_SETTINGS_KEYS

    def test_value_types(self):
        data = fetch().json()
        for key in PUBLIC_SETTINGS_INT_KEYS:
            assert isinstance(data[key], int) and not isinstance(data[key], bool), key
        assert isinstance(data["timezone"], str)
        assert isinstance(data["server_now"], str)

    def test_response_is_not_in_error_format(self):
        assert not (ERROR_KEYS <= set(fetch().json()))

    def test_values_match_the_database(self):
        row = PlatformSetting.objects.get(pk=1)
        data = fetch().json()
        for key in PUBLIC_SETTINGS_INT_KEYS | {"timezone"}:
            assert data[key] == getattr(row, key), key

    def test_documented_defaults(self):
        data = fetch().json()
        assert data["timezone"] == PLATFORM_TIMEZONE
        assert data["closing_soon_threshold_minutes"] == 60
        assert data["order_cutoff_before_close_minutes"] == 30
        assert data["max_quantity_per_order"] == 3

    @pytest.mark.parametrize(
        "field,new_value",
        [
            ("order_response_timeout_minutes", 16),
            ("order_pickup_timeout_minutes", 90),
            ("order_cutoff_before_close_minutes", 45),
            ("closing_soon_threshold_minutes", 90),
            ("max_quantity_per_order", 5),
            ("max_active_orders_per_customer", 2),
            ("no_show_threshold", 4),
            ("no_show_window_days", 45),
            ("suspension_duration_days", 14),
        ],
    )
    def test_each_setting_reflects_database_changes_immediately(self, field, new_value):
        assert fetch().json()[field] != new_value
        PlatformSetting.objects.filter(pk=1).update(**{field: new_value})
        assert fetch().json()[field] == new_value

    def test_timezone_reflects_database_changes(self):
        PlatformSetting.objects.filter(pk=1).update(timezone="Europe/Paris")
        assert fetch().json()["timezone"] == "Europe/Paris"

    def test_authenticated_user_sees_the_same_data(self, auth_client, customer):
        anonymous = fetch().json()
        authenticated = auth_client(customer).get(URL_PUBLIC_SETTINGS).json()
        anonymous.pop("server_now"), authenticated.pop("server_now")
        assert anonymous == authenticated

    def test_no_internal_fields_are_exposed(self):
        text = fetch().content.decode()
        for internal in ("updated_at", "created_at", '"id"'):
            assert internal not in text


# ==========================================================================
# server_now
# ==========================================================================
class TestServerNow:
    def test_matches_the_frozen_instant(self):
        instant = douala(2026, 3, 4, 19, 30)  # 18:30 UTC
        with freeze_time(instant):
            value = fetch().json()["server_now"]
        assert parse_datetime(value) == instant

    def test_is_expressed_in_utc_not_in_platform_time(self):
        with freeze_time(douala(2026, 3, 4, 19, 30)):
            value = fetch().json()["server_now"]
        parsed = parse_datetime(value)
        assert parsed is not None and parsed.utcoffset() == timedelta(0)
        assert "18:30" in value

    def test_advances_between_two_calls(self):
        with freeze_time("2026-03-04 10:00:00"):
            first = parse_datetime(fetch().json()["server_now"])
        with freeze_time("2026-03-04 10:00:07"):
            second = parse_datetime(fetch().json()["server_now"])
        assert second - first == timedelta(seconds=7)

    def test_is_close_to_the_real_clock(self):
        value = parse_datetime(fetch().json()["server_now"])
        assert abs(datetime.now(dt_timezone.utc) - value) < timedelta(seconds=10)

    def test_is_timezone_aware(self):
        assert parse_datetime(fetch().json()["server_now"]).tzinfo is not None


# ==========================================================================
# Accès, méthodes, cache, robustesse
# ==========================================================================
class TestPublicSettingsAccess:
    def test_garbage_bearer_header_does_not_block_a_public_endpoint(self):
        client = APIClient()
        bearer(client, "ceci.n.est.pas.un.jwt")
        assert fetch(client).status_code == 200

    def test_expired_bearer_header_does_not_block_a_public_endpoint(self, customer):
        token = services.issue_auth_tokens(user=customer).access_token
        client = APIClient()
        bearer(client, token)
        later = datetime.now(dt_timezone.utc) + jwt_settings.ACCESS_TOKEN_LIFETIME + timedelta(minutes=5)
        with freeze_time(later):
            assert fetch(client).status_code == 200

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_write_methods_are_405(self, method):
        r = getattr(APIClient(), method)(URL_PUBLIC_SETTINGS, data={}, format="json")
        assert_unified_error(r, 405)
        assert PlatformSetting.objects.get(pk=1).timezone == PLATFORM_TIMEZONE

    def test_response_cannot_be_cached_publicly(self):
        """server_now doit rester frais : ni `public`, ni max-age > 0."""
        cache_control = fetch().get("Cache-Control", "").lower()
        assert "public" not in cache_control
        for part in cache_control.split(","):
            part = part.strip()
            if part.startswith("max-age="):
                assert int(part.split("=")[1]) == 0

    def test_query_count_is_small(self, django_assert_max_num_queries):
        with django_assert_max_num_queries(2):
            assert fetch().status_code == 200

    def test_repeated_calls_are_stable(self):
        first, second = fetch().json(), fetch().json()
        first.pop("server_now"), second.pop("server_now")
        assert first == second

    def test_missing_singleton_never_causes_a_500(self):
        PlatformSetting.objects.all().delete()
        client = APIClient()
        client.raise_request_exception = False
        assert client.get(URL_PUBLIC_SETTINGS).status_code in (200, 503)
