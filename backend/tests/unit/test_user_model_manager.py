"""Modèle User et UserManager.

Pièges ciblés sur le téléphone E.164 :
- `$` en regex Python accepte un "\\n" final (il faut `\\Z`) ;
- `\\d` accepte les chiffres Unicode (arabes-indiens, pleine largeur) sans re.ASCII.
Un échec sur ces cas est un vrai finding de sécurité/qualité des données.
"""
import itertools
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from freezegun import freeze_time

from apps.accounts.models import User, UserRole
from tests.constants import VALID_PASSWORD
from tests.helpers import create_user

pytestmark = [pytest.mark.unit, pytest.mark.django_db]

_seq = itertools.count(9000)


def direct_create(**overrides):
    """Appel direct du manager, sans rôle imposé par le helper."""
    n = next(_seq)
    data = dict(
        email=f"direct{n}@example.com",
        phone=f"+22508{n:08d}",
        full_name=f"Direct {n}",
        password=VALID_PASSWORD,
    )
    data.update(overrides)
    return User.objects.create_user(**data)


def field_errors(obj):
    with pytest.raises(ValidationError) as exc:
        obj.full_clean()
    return exc.value.message_dict


# --------------------------------------------------------------------------
# Configuration du modèle
# --------------------------------------------------------------------------
def test_user_is_the_auth_user_model():
    assert get_user_model() is User


def test_username_field_is_email():
    assert User.USERNAME_FIELD == "email"


def test_roles_are_exactly_the_three_documented_ones():
    assert {value for value, _ in UserRole.choices} == {"CUSTOMER", "DEPOT_MANAGER", "ADMIN"}


def test_pk_is_a_uuid(customer):
    assert isinstance(customer.pk, uuid.UUID)


def test_str_is_not_empty_and_does_not_expose_password_hash(customer):
    text = str(customer)
    assert text.strip() != ""
    assert customer.password not in text


# --------------------------------------------------------------------------
# create_user
# --------------------------------------------------------------------------
class TestCreateUser:
    def test_returns_persisted_user_with_given_fields(self):
        user = direct_create(email="amina@example.com", phone="+2250102030405", full_name="Amina Koné")
        stored = User.objects.get(pk=user.pk)
        assert (stored.email, stored.phone, stored.full_name) == (
            "amina@example.com",
            "+2250102030405",
            "Amina Koné",
        )

    def test_default_role_is_customer(self):
        assert direct_create().role == UserRole.CUSTOMER

    def test_default_flags(self):
        user = direct_create()
        assert user.is_active is True
        assert user.is_staff is False
        assert user.is_superuser is False

    def test_password_is_hashed_and_verifiable(self):
        user = direct_create(password=VALID_PASSWORD)
        assert user.password != VALID_PASSWORD
        assert VALID_PASSWORD not in user.password
        assert user.check_password(VALID_PASSWORD)
        assert not user.check_password(VALID_PASSWORD + "x")

    def test_password_none_gives_unusable_password(self):
        user = direct_create(password=None)
        assert user.has_usable_password() is False

    def test_email_domain_is_normalized_to_lowercase(self):
        user = direct_create(email="Jean.Kouame@EXAMPLE.COM")
        assert user.email.split("@")[1] == "example.com"

    @pytest.mark.parametrize("role", [r for r, _ in UserRole.choices])
    def test_each_role_can_be_assigned(self, role):
        assert direct_create(role=role).role == role

    def test_email_is_required(self):
        with pytest.raises((ValueError, ValidationError)):
            direct_create(email="")

    def test_extra_fields_are_applied(self):
        assert direct_create(is_staff=True).is_staff is True


# --------------------------------------------------------------------------
# create_superuser
# --------------------------------------------------------------------------
class TestCreateSuperuser:
    def _create(self, **overrides):
        n = next(_seq)
        data = dict(
            email=f"root{n}@example.com",
            phone=f"+22509{n:08d}",
            full_name="Root",
            password=VALID_PASSWORD,
        )
        data.update(overrides)
        return User.objects.create_superuser(**data)

    def test_flags_are_set(self):
        user = self._create()
        assert user.is_staff is True
        assert user.is_superuser is True
        assert user.is_active is True

    def test_role_is_admin_for_consistency(self):
        """Un superuser avec role=CUSTOMER serait une incohérence de modèle."""
        assert self._create().role == UserRole.ADMIN

    def test_password_is_hashed(self):
        user = self._create()
        assert user.password != VALID_PASSWORD and user.check_password(VALID_PASSWORD)

    def test_refuses_is_staff_false(self):
        with pytest.raises(ValueError):
            self._create(is_staff=False)

    def test_refuses_is_superuser_false(self):
        with pytest.raises(ValueError):
            self._create(is_superuser=False)


# --------------------------------------------------------------------------
# Validation email
# --------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["pas-un-email", "a@", "@b.com", "a b@example.com", ""])
def test_invalid_email_is_rejected_by_full_clean(customer, bad):
    customer.email = bad
    assert "email" in field_errors(customer)


def test_duplicate_email_is_rejected_by_validate_unique(customer, other_customer):
    other_customer.email = customer.email
    assert "email" in field_errors(other_customer)


# --------------------------------------------------------------------------
# Validation téléphone E.164  ^\+[1-9]\d{7,14}$
# --------------------------------------------------------------------------
def _digits(prefix, base):
    return "+" + "".join(chr(base + int(d)) for d in "2250102030405")


VALID_PHONES = [
    "+2250102030405",
    "+12025550123",
    "+33612345678",
    "+12345678",            # 8 chiffres : borne basse
    "+123456789012345",     # 15 chiffres : borne haute
]

INVALID_PHONES = {
    "sans_plus": "2250102030405",
    "zero_local": "0102030405",
    "double_zero": "00225102030405",
    "plus_puis_zero": "+0225102030405",
    "7_chiffres": "+1234567",
    "16_chiffres": "+1234567890123456",
    "espaces": "+225 01 02 03 04 05",
    "tirets": "+225-01-02-03-04-05",
    "vide": "",
    "plus_seul": "+",
    "double_plus": "++2250102030405",
    "lettres": "+225abcdefgh",
    "parentheses": "+(225)0102030405",
    "espace_devant": " +2250102030405",
    "espace_derriere": "+2250102030405 ",
    "newline_final": "+2250102030405\n",                 # piège `$` vs `\Z`
    "chiffres_arabes_indiens": _digits("+", 0x0660),      # piège `\d` Unicode
    "chiffres_pleine_largeur": _digits("+", 0xFF10),      # piège `\d` Unicode
}


@pytest.mark.parametrize("phone", VALID_PHONES)
def test_valid_e164_phones_are_accepted(customer, phone):
    customer.phone = phone
    customer.full_clean()


@pytest.mark.parametrize("phone", list(INVALID_PHONES.values()), ids=list(INVALID_PHONES.keys()))
def test_invalid_phones_are_rejected(customer, phone):
    customer.phone = phone
    assert "phone" in field_errors(customer)


def test_duplicate_phone_is_rejected_by_validate_unique(customer, other_customer):
    other_customer.phone = customer.phone
    assert "phone" in field_errors(other_customer)


# --------------------------------------------------------------------------
# full_name / role
# --------------------------------------------------------------------------
def test_empty_full_name_is_rejected(customer):
    customer.full_name = ""
    assert "full_name" in field_errors(customer)


def test_full_name_longer_than_max_length_is_rejected(customer):
    max_length = User._meta.get_field("full_name").max_length
    if not max_length:
        pytest.skip("full_name sans max_length")
    customer.full_name = "x" * (max_length + 1)
    assert "full_name" in field_errors(customer)


def test_unicode_full_name_round_trips(customer):
    name = "Kouamé N'Guessan-Ouédraogo 🙂"
    customer.full_name = name
    customer.full_clean()
    customer.save()
    customer.refresh_from_db()
    assert customer.full_name == name


@pytest.mark.parametrize("bad_role", ["HACKER", "customer", "", "SUPERADMIN"])
def test_unknown_role_is_rejected(customer, bad_role):
    customer.role = bad_role
    assert "role" in field_errors(customer)


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------
def test_timestamps_are_timezone_aware(customer):
    assert customer.created_at.tzinfo is not None
    assert customer.updated_at.tzinfo is not None


def test_updated_at_moves_on_save_but_created_at_does_not():
    with freeze_time("2026-03-01 10:00:00") as frozen:
        user = create_user()
        created = user.created_at
        frozen.move_to("2026-03-01 11:00:00")
        user.full_name = "Nouveau nom"
        user.save()
    user.refresh_from_db()
    assert user.created_at == created
    assert user.updated_at > created


# --------------------------------------------------------------------------
# Unicité insensible à la casse (hypothèse n°6, durcissement)
# --------------------------------------------------------------------------
def test_emails_differing_only_by_case_cannot_coexist():
    from django.db import IntegrityError, transaction

    create_user(email="Alice.Case@Example.com")
    with pytest.raises((IntegrityError, ValidationError)):
        with transaction.atomic():
            create_user(email="alice.case@example.com")
