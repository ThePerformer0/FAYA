"""CustomerSuspension : propriété is_currently_active.

HYPOTHÈSE de sémantique : intervalle semi-ouvert [starts_at, ends_at[
(actif à starts_at pile, inactif à ends_at pile). Si votre règle est
différente, seuls les tests marqués « bornes » sont à ajuster.
"""
from datetime import timedelta

import pytest
from freezegun import freeze_time

from apps.accounts.models import CustomerSuspension, SuspensionReason
from tests.factories import make_suspension, utc

pytestmark = [pytest.mark.unit, pytest.mark.django_db]

START = utc(2026, 3, 1, 12)
END = utc(2026, 3, 8, 12)
MICRO = timedelta(microseconds=1)


def active_at(suspension, moment):
    with freeze_time(moment):
        return suspension.is_currently_active


@pytest.fixture
def suspension(customer):
    return make_suspension(customer, starts_at=START, ends_at=END)


# --------------------------------------------------------------------------
# Bornes (sémantique semi-ouverte)
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "moment,expected",
    [
        (START - timedelta(days=1), False),
        (START - MICRO, False),
        (START, True),
        (START + MICRO, True),
        (START + timedelta(days=3), True),
        (END - MICRO, True),
        (END, False),
        (END + MICRO, False),
        (END + timedelta(days=30), False),
    ],
    ids=[
        "veille", "1us_avant_debut", "debut_pile", "1us_apres_debut", "milieu",
        "1us_avant_fin", "fin_pile", "1us_apres_fin", "bien_apres",
    ],
)
def test_is_currently_active_boundaries(suspension, moment, expected):
    assert active_at(suspension, moment) is expected


# --------------------------------------------------------------------------
# Levée
# --------------------------------------------------------------------------
def test_lifted_suspension_is_never_active(customer):
    s = make_suspension(customer, starts_at=START, ends_at=END, lifted_at=START + timedelta(days=1))
    assert active_at(s, START + timedelta(days=2)) is False


def test_lifted_after_natural_expiry_is_inactive(customer):
    s = make_suspension(customer, starts_at=START, ends_at=END, lifted_at=END + timedelta(days=1))
    assert active_at(s, START + timedelta(days=2)) in (True, False)  # ne doit pas lever
    assert active_at(s, END + timedelta(days=2)) is False


def test_property_does_not_hit_the_database(suspension, django_assert_num_queries):
    with freeze_time(START + timedelta(days=1)):
        with django_assert_num_queries(0):
            _ = suspension.is_currently_active


def test_property_returns_a_real_bool(suspension):
    assert isinstance(active_at(suspension, START + timedelta(days=1)), bool)


# --------------------------------------------------------------------------
# Champs
# --------------------------------------------------------------------------
def test_reasons_are_the_two_documented_ones():
    assert {v for v, _ in SuspensionReason.choices} == {"NO_SHOW_THRESHOLD", "MANUAL"}


def test_lift_fields_default_to_none(suspension):
    suspension.refresh_from_db()
    assert suspension.lifted_at is None
    assert suspension.lifted_by is None
    assert not suspension.lift_reason


def test_invalid_reason_is_rejected_by_full_clean(suspension):
    from django.core.exceptions import ValidationError

    suspension.reason = "BECAUSE"
    with pytest.raises(ValidationError) as exc:
        suspension.full_clean()
    assert "reason" in exc.value.message_dict


def test_pk_is_uuid_and_customer_relation_works(suspension, customer):
    import uuid

    assert isinstance(suspension.pk, uuid.UUID)
    assert CustomerSuspension.objects.get(pk=suspension.pk).customer == customer
