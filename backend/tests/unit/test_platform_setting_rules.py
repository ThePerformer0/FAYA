"""Règles de validation du singleton PlatformSetting (couche Django : full_clean)."""
import pytest
from django.core.exceptions import ObjectDoesNotExist, ValidationError

from apps.core.models import PlatformSetting

pytestmark = [pytest.mark.unit, pytest.mark.django_db]

DEFAULTS = {
    "timezone": "Africa/Abidjan",
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


def configured(**overrides):
    obj = PlatformSetting.load()
    for key, value in overrides.items():
        setattr(obj, key, value)
    return obj


# --------------------------------------------------------------------------
# Valeurs par défaut / singleton
# --------------------------------------------------------------------------
@pytest.mark.parametrize("field,expected", list(DEFAULTS.items()))
def test_in_memory_defaults(field, expected):
    assert getattr(PlatformSetting(), field) == expected


def test_load_returns_singleton_with_id_1(platform_setting):
    assert PlatformSetting.load().pk == 1


def test_load_is_idempotent_and_never_duplicates(platform_setting):
    first = PlatformSetting.load()
    second = PlatformSetting.load()
    assert first.pk == second.pk == 1
    assert PlatformSetting.objects.count() == 1


def test_load_reflects_persisted_changes(platform_setting):
    platform_setting.max_quantity_per_order = 5
    platform_setting.save()
    assert PlatformSetting.load().max_quantity_per_order == 5


def test_load_after_row_deletion_never_returns_another_id(platform_setting):
    """Soit load() recrée la ligne id=1, soit il lève une erreur explicite ; jamais id != 1."""
    PlatformSetting.objects.all().delete()
    try:
        obj = PlatformSetting.load()
    except ObjectDoesNotExist:
        return
    assert obj.pk == 1
    assert PlatformSetting.objects.count() == 1


def test_default_configuration_passes_full_clean(platform_setting):
    PlatformSetting.load().full_clean()


# --------------------------------------------------------------------------
# Bornes des champs numériques (> 0)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("field", NUMERIC_FIELDS)
@pytest.mark.parametrize("bad_value", [0, -1, -100])
def test_numeric_fields_must_be_strictly_positive(platform_setting, field, bad_value):
    with pytest.raises(ValidationError):
        configured(**{field: bad_value}).full_clean()


@pytest.mark.parametrize("field", NUMERIC_FIELDS)
def test_numeric_fields_reject_null(platform_setting, field):
    with pytest.raises(ValidationError):
        configured(**{field: None}).full_clean()


@pytest.mark.parametrize("field", NUMERIC_FIELDS)
def test_numeric_fields_reject_non_numeric(platform_setting, field):
    with pytest.raises(ValidationError):
        configured(**{field: "abc"}).full_clean()


@pytest.mark.parametrize("field", NUMERIC_FIELDS)
def test_numeric_fields_accept_lower_bound_one(platform_setting, field):
    overrides = {field: 1}
    if field == "order_cutoff_before_close_minutes":
        overrides["order_response_timeout_minutes"] = 1  # garder cutoff >= timeout
    configured(**overrides).full_clean()


# --------------------------------------------------------------------------
# Règle : order_cutoff_before_close_minutes >= order_response_timeout_minutes
# --------------------------------------------------------------------------
def test_cutoff_equal_to_timeout_is_valid(platform_setting):
    configured(
        order_response_timeout_minutes=30, order_cutoff_before_close_minutes=30
    ).full_clean()


def test_cutoff_one_below_timeout_is_invalid(platform_setting):
    with pytest.raises(ValidationError):
        configured(
            order_response_timeout_minutes=15, order_cutoff_before_close_minutes=14
        ).full_clean()


def test_lowering_cutoff_below_current_timeout_is_invalid(platform_setting):
    with pytest.raises(ValidationError):
        configured(order_cutoff_before_close_minutes=1).full_clean()


def test_raising_timeout_above_current_cutoff_is_invalid(platform_setting):
    with pytest.raises(ValidationError):
        configured(order_response_timeout_minutes=31).full_clean()


def test_raising_both_values_keeping_rule_is_valid(platform_setting):
    configured(
        order_response_timeout_minutes=45, order_cutoff_before_close_minutes=60
    ).full_clean()


# --------------------------------------------------------------------------
# Timezone (durcissement : un fuseau inventé ne doit pas être accepté)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("tz", ["Africa/Abidjan", "Europe/Paris", "UTC"])
def test_valid_timezones_are_accepted(platform_setting, tz):
    configured(timezone=tz).full_clean()


@pytest.mark.parametrize("tz", ["Mars/Olympus", "", "pas un fuseau", "Africa/"])
def test_invalid_timezones_are_rejected(platform_setting, tz):
    with pytest.raises(ValidationError):
        configured(timezone=tz).full_clean()
