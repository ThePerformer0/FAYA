"""Contraintes PostgreSQL du module accounts (unicité, NOT NULL, ends_at > starts_at, FK).

Pattern : `pytest.raises` à l'extérieur, `transaction.atomic()` à l'intérieur.
"""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.accounts.models import CustomerSuspension, User
from tests.factories import make_suspension, utc
from tests.helpers import create_user

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

START = utc(2026, 3, 1, 12)
END = utc(2026, 3, 8, 12)


# --------------------------------------------------------------------------
# User : unicité
# --------------------------------------------------------------------------
def test_duplicate_email_is_refused_by_the_database(customer):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            create_user(email=customer.email)


def test_duplicate_phone_is_refused_by_the_database(customer):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            create_user(phone=customer.phone)


def test_emails_differing_only_by_case_are_refused():
    """Hypothèse n°6 (durcissement) : unicité insensible à la casse."""
    create_user(email="Bob.Dupont@Example.com")
    with pytest.raises((IntegrityError, ValidationError)):
        with transaction.atomic():
            create_user(email="bob.dupont@example.com")


def test_two_users_cannot_share_an_empty_phone(customer, other_customer):
    User.objects.filter(pk=customer.pk).update(phone="")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.filter(pk=other_customer.pk).update(phone="")


# --------------------------------------------------------------------------
# User : NOT NULL
# --------------------------------------------------------------------------
@pytest.mark.parametrize("field", ["email", "phone", "full_name"])
def test_required_columns_reject_null(customer, field):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            User.objects.filter(pk=customer.pk).update(**{field: None})


# --------------------------------------------------------------------------
# CustomerSuspension : ends_at > starts_at
# --------------------------------------------------------------------------
def test_suspension_with_ends_equal_starts_is_refused(customer):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_suspension(customer, starts_at=START, ends_at=START)


def test_suspension_with_ends_before_starts_is_refused(customer):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            make_suspension(customer, starts_at=START, ends_at=START - timedelta(seconds=1))


def test_suspension_with_ends_one_microsecond_after_starts_is_accepted(customer):
    s = make_suspension(customer, starts_at=START, ends_at=START + timedelta(microseconds=1))
    assert CustomerSuspension.objects.filter(pk=s.pk).exists()


def test_constraint_also_applies_to_updates(customer):
    s = make_suspension(customer, starts_at=START, ends_at=END)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CustomerSuspension.objects.filter(pk=s.pk).update(ends_at=START)
    s.refresh_from_db()
    assert s.ends_at == END


def test_constraint_applies_to_raw_queryset_bypassing_full_clean(customer):
    s = make_suspension(customer, starts_at=START, ends_at=END)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            CustomerSuspension.objects.filter(pk=s.pk).update(starts_at=END + timedelta(days=1))


# --------------------------------------------------------------------------
# CustomerSuspension : conservation de l'historique
# --------------------------------------------------------------------------
def test_suspension_survives_deletion_of_the_admin_who_lifted_it(customer, admin_user):
    s = make_suspension(
        customer,
        starts_at=START,
        ends_at=END,
        lifted_at=START + timedelta(days=1),
        lifted_by=admin_user,
        lift_reason="geste commercial",
    )
    try:
        with transaction.atomic():
            admin_user.delete()
    except ProtectedError:
        pass  # PROTECT est acceptable
    assert CustomerSuspension.objects.filter(pk=s.pk).exists(), (
        "supprimer l'admin qui a levé la suspension a détruit la suspension (CASCADE ?)"
    )
