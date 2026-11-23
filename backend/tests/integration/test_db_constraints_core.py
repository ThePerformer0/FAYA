"""Contraintes SQL de PlatformSetting, indépendantes de la validation Django.

On contourne volontairement full_clean() (QuerySet.update, SQL brut) pour
prouver que PostgreSQL protège les règles métier.
NB : pattern `pytest.raises` à l'extérieur, `transaction.atomic()` à l'intérieur,
pour que le savepoint soit annulé avant la capture de l'erreur.
"""
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction

from apps.core.models import PlatformSetting

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

DEFAULTS = {
    "timezone": "Africa/Douala",
    "order_response_timeout_minutes": 15,
    "order_pickup_timeout_minutes": 120,
    "order_cutoff_before_close_minutes": 30,
    "max_quantity_per_order": 3,
    "max_active_orders_per_customer": 1,
    "no_show_threshold": 3,
    "no_show_window_days": 30,
    "suspension_duration_days": 7,
}
NUMERIC_FIELDS = [name for name in DEFAULTS if name != "timezone"]


# --------------------------------------------------------------------------
# Singleton créé par la migration
# --------------------------------------------------------------------------
def test_migration_created_the_singleton_row():
    assert PlatformSetting.objects.filter(pk=1).exists()
    assert PlatformSetting.objects.count() == 1


@pytest.mark.parametrize("field,expected", list(DEFAULTS.items()))
def test_migrated_row_has_documented_defaults(field, expected):
    assert getattr(PlatformSetting.objects.get(pk=1), field) == expected


def test_second_row_is_refused():
    """Durcissement : le singleton ne doit pas pouvoir être dupliqué."""
    with pytest.raises((IntegrityError, ValidationError)):
        with transaction.atomic():
            PlatformSetting.objects.create(id=2)
    assert PlatformSetting.objects.count() == 1


def test_saving_the_singleton_again_updates_in_place():
    obj = PlatformSetting.load()
    obj.max_quantity_per_order = 4
    obj.save()
    assert PlatformSetting.objects.count() == 1
    assert PlatformSetting.objects.get(pk=1).max_quantity_per_order == 4


# --------------------------------------------------------------------------
# Contraintes CHECK (> 0)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("field", NUMERIC_FIELDS)
@pytest.mark.parametrize("bad_value", [0, -1])
def test_db_rejects_non_positive_values_via_queryset_update(field, bad_value):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PlatformSetting.objects.filter(pk=1).update(**{field: bad_value})
    assert getattr(PlatformSetting.objects.get(pk=1), field) == DEFAULTS[field]


@pytest.mark.parametrize("field", NUMERIC_FIELDS)
def test_db_rejects_zero_via_raw_sql(field):
    table = PlatformSetting._meta.db_table
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'UPDATE "{table}" SET "{field}" = 0 WHERE id = 1')


# --------------------------------------------------------------------------
# Contrainte CHECK : cutoff >= response timeout
# --------------------------------------------------------------------------
def test_db_rejects_cutoff_below_timeout_via_queryset_update():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PlatformSetting.objects.filter(pk=1).update(order_cutoff_before_close_minutes=14)


def test_db_rejects_timeout_above_cutoff_via_queryset_update():
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PlatformSetting.objects.filter(pk=1).update(order_response_timeout_minutes=31)


def test_db_rejects_cutoff_below_timeout_via_raw_sql():
    table = PlatformSetting._meta.db_table
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    f'UPDATE "{table}" SET order_cutoff_before_close_minutes = 1, '
                    f"order_response_timeout_minutes = 15 WHERE id = 1"
                )


def test_db_accepts_cutoff_equal_to_timeout():
    PlatformSetting.objects.filter(pk=1).update(
        order_response_timeout_minutes=30, order_cutoff_before_close_minutes=30
    )
    obj = PlatformSetting.objects.get(pk=1)
    assert obj.order_response_timeout_minutes == obj.order_cutoff_before_close_minutes == 30


def test_save_of_invalid_cutoff_is_blocked_by_model_or_db():
    obj = PlatformSetting.load()
    obj.order_cutoff_before_close_minutes = 1
    with pytest.raises((ValidationError, IntegrityError)):
        with transaction.atomic():
            obj.save()
    assert PlatformSetting.objects.get(pk=1).order_cutoff_before_close_minutes == 30
