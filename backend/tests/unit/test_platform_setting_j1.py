"""PlatformSetting, ajouts du Jalon 1 : fuseau Africa/Douala et closing_soon_threshold_minutes."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from apps.core.models import PlatformSetting
from tests.constants_j1 import PLATFORM_TIMEZONE

pytestmark = [pytest.mark.unit, pytest.mark.django_db]


def configured(**overrides):
    obj = PlatformSetting.load()
    for key, value in overrides.items():
        setattr(obj, key, value)
    return obj


# --------------------------------------------------------------------------
# Valeurs par défaut et donnée migrée
# --------------------------------------------------------------------------
class TestDefaults:
    def test_in_memory_defaults(self):
        obj = PlatformSetting()
        assert obj.timezone == PLATFORM_TIMEZONE
        assert obj.closing_soon_threshold_minutes == 60
        assert obj.order_cutoff_before_close_minutes == 30

    def test_migrated_singleton_row_was_updated_to_douala(self):
        """Si la migration ne touche que le défaut du champ, la prod reste sur l'ancien fuseau."""
        row = PlatformSetting.objects.get(pk=1)
        assert row.timezone == PLATFORM_TIMEZONE
        assert row.closing_soon_threshold_minutes == 60
        assert row.order_cutoff_before_close_minutes == 30

    def test_load_returns_the_migrated_values(self):
        loaded = PlatformSetting.load()
        assert (loaded.pk, loaded.timezone, loaded.closing_soon_threshold_minutes) == (1, PLATFORM_TIMEZONE, 60)

    @pytest.mark.parametrize("moment", [datetime(2026, 1, 15, 12), datetime(2026, 7, 15, 12)],
                             ids=["janvier", "juillet"])
    def test_platform_timezone_is_utc_plus_one_all_year(self, moment):
        assert ZoneInfo(PlatformSetting.load().timezone).utcoffset(moment) == timedelta(hours=1)

    def test_default_configuration_passes_full_clean(self):
        PlatformSetting.load().full_clean()


# --------------------------------------------------------------------------
# closing_soon_threshold_minutes : validation Django
# --------------------------------------------------------------------------
class TestThresholdValidation:
    @pytest.mark.parametrize("bad", [0, -1, -60, None, "abc"], ids=["zero", "moins1", "moins60", "null", "texte"])
    def test_invalid_values_are_rejected(self, bad):
        with pytest.raises(ValidationError) as exc:
            configured(closing_soon_threshold_minutes=bad).full_clean()
        assert "closing_soon_threshold_minutes" in exc.value.message_dict or "__all__" in exc.value.message_dict

    @pytest.mark.parametrize("good", [1, 15, 60, 120, 1440])
    def test_positive_values_are_accepted(self, good):
        configured(closing_soon_threshold_minutes=good).full_clean()

    @pytest.mark.parametrize("threshold", [10, 30, 45])
    def test_threshold_may_be_lower_than_or_equal_to_the_order_cutoff(self, threshold):
        """Aucune règle ne lie les deux : CLOSING_SOON vient aussi de can_order=False."""
        configured(closing_soon_threshold_minutes=threshold, order_cutoff_before_close_minutes=30).full_clean()

    def test_existing_cutoff_rule_still_applies(self):
        with pytest.raises(ValidationError):
            configured(order_response_timeout_minutes=15, order_cutoff_before_close_minutes=14).full_clean()

    def test_changing_the_threshold_does_not_disturb_other_fields(self):
        before = PlatformSetting.load()
        before.closing_soon_threshold_minutes = 90
        before.save()
        after = PlatformSetting.load()
        assert after.closing_soon_threshold_minutes == 90
        assert after.order_cutoff_before_close_minutes == 30
        assert after.timezone == PLATFORM_TIMEZONE


# --------------------------------------------------------------------------
# closing_soon_threshold_minutes : contrainte SQL (indépendante de full_clean)
# --------------------------------------------------------------------------
class TestThresholdSqlConstraint:
    @pytest.mark.parametrize("bad", [0, -1])
    def test_db_rejects_non_positive_via_queryset_update(self, bad):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PlatformSetting.objects.filter(pk=1).update(closing_soon_threshold_minutes=bad)
        assert PlatformSetting.objects.get(pk=1).closing_soon_threshold_minutes == 60

    def test_db_rejects_zero_via_raw_sql(self):
        table = PlatformSetting._meta.db_table
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f'UPDATE "{table}" SET closing_soon_threshold_minutes = 0 WHERE id = 1')

    def test_db_rejects_null(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PlatformSetting.objects.filter(pk=1).update(closing_soon_threshold_minutes=None)

    def test_db_accepts_a_threshold_below_the_cutoff(self):
        PlatformSetting.objects.filter(pk=1).update(closing_soon_threshold_minutes=10)
        assert PlatformSetting.objects.get(pk=1).closing_soon_threshold_minutes == 10

    def test_save_of_an_invalid_threshold_is_blocked_by_model_or_db(self):
        obj = PlatformSetting.load()
        obj.closing_soon_threshold_minutes = 0
        with pytest.raises((ValidationError, IntegrityError)):
            with transaction.atomic():
                obj.save()
        assert PlatformSetting.objects.get(pk=1).closing_soon_threshold_minutes == 60


# --------------------------------------------------------------------------
# Fuseau
# --------------------------------------------------------------------------
class TestTimezoneField:
    @pytest.mark.parametrize("tz", [PLATFORM_TIMEZONE, "Europe/Paris", "UTC", "Africa/Abidjan"])
    def test_valid_zones_are_accepted(self, tz):
        configured(timezone=tz).full_clean()

    @pytest.mark.parametrize("tz", ["Mars/Olympus", "", "UTC+1", "Douala", "Africa/"])
    def test_invalid_zones_are_rejected(self, tz):
        with pytest.raises(ValidationError):
            configured(timezone=tz).full_clean()
