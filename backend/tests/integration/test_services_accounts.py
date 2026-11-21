"""Services accounts : register_customer, authenticate_user, update_profile.

Les classes `*ServiceLevelValidation` vérifient la défense en profondeur : si
le service ne valide pas lui-même (validation uniquement côté serializer), ces
tests échouent -> finding de durcissement, pas forcément un bug fonctionnel.
"""
import inspect
import itertools

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from freezegun import freeze_time

from apps.accounts import services
from apps.accounts.models import User, UserRole
from apps.core.exceptions import (
    AuthenticationDomainError,
    ConflictDomainError,
    ValidationDomainError,
)
from tests.constants import (
    CODE_ACCOUNT_DISABLED,
    CODE_ACCOUNT_ALREADY_EXISTS,
    CODE_EMAIL_ALREADY_EXISTS,
    CODE_INVALID_CREDENTIALS,
    CODE_PHONE_ALREADY_EXISTS,
    PASSWORD_ALL_NUMERIC,
    PASSWORD_COMMON,
    PASSWORD_TOO_SHORT,
    VALID_PASSWORD,
)
from tests.domain_asserts import assert_domain_error, code_of, message_of
from tests.helpers import create_user

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

VALIDATION_ERRORS = (ValidationDomainError, DjangoValidationError)
_seq = itertools.count(50000)


def registration_data(**overrides):
    n = next(_seq)
    data = dict(
        email=f"new{n}@example.com",
        phone=f"+22501{n:08d}",
        full_name="Nouvelle Cliente",
        password=VALID_PASSWORD,
    )
    data.update(overrides)
    return data


# ==========================================================================
# register_customer
# ==========================================================================
class TestRegisterCustomer:
    def test_creates_a_customer_with_safe_defaults(self):
        data = registration_data()
        user = services.register_customer(**data)
        stored = User.objects.get(pk=user.pk)
        assert stored.email.lower() == data["email"].lower()
        assert stored.phone == data["phone"]
        assert stored.full_name == data["full_name"]
        assert stored.role == UserRole.CUSTOMER
        assert stored.is_active is True
        assert stored.is_staff is False
        assert stored.is_superuser is False

    def test_password_is_hashed_and_verifiable(self):
        user = services.register_customer(**registration_data())
        assert user.password != VALID_PASSWORD
        assert user.check_password(VALID_PASSWORD)

    def test_signature_exposes_only_documented_parameters(self):
        params = set(inspect.signature(services.register_customer).parameters)
        assert params == {"email", "phone", "full_name", "password"}

    @pytest.mark.parametrize("extra", [{"role": "ADMIN"}, {"is_staff": True}, {"is_superuser": True}])
    def test_privileged_fields_cannot_be_injected(self, extra):
        with pytest.raises(TypeError):
            services.register_customer(**registration_data(), **extra)

    def test_arguments_are_keyword_only(self):
        d = registration_data()
        with pytest.raises(TypeError):
            services.register_customer(d["email"], d["phone"], d["full_name"], d["password"])

    def test_duplicate_email_raises_conflict(self, customer):
        before = User.objects.count()
        with pytest.raises(ConflictDomainError) as exc:
            services.register_customer(**registration_data(email=customer.email))
        assert_domain_error(exc, ConflictDomainError, CODE_EMAIL_ALREADY_EXISTS)
        assert User.objects.count() == before

    def test_duplicate_email_differing_by_case_raises_conflict(self, customer):
        with pytest.raises(ConflictDomainError) as exc:
            services.register_customer(**registration_data(email=customer.email.upper()))
        assert_domain_error(exc, ConflictDomainError, CODE_EMAIL_ALREADY_EXISTS)

    def test_duplicate_phone_raises_conflict(self, customer):
        before = User.objects.count()
        with pytest.raises(ConflictDomainError) as exc:
            services.register_customer(**registration_data(phone=customer.phone))
        assert_domain_error(exc, ConflictDomainError, CODE_PHONE_ALREADY_EXISTS)
        assert User.objects.count() == before

    def test_duplicate_email_and_phone_raises_a_conflict_code(self, customer):
        with pytest.raises(ConflictDomainError) as exc:
            services.register_customer(
                **registration_data(email=customer.email, phone=customer.phone)
            )
        assert code_of(exc.value) in {
            CODE_EMAIL_ALREADY_EXISTS,
            CODE_PHONE_ALREADY_EXISTS,
            CODE_ACCOUNT_ALREADY_EXISTS,
        }

    def test_failed_registration_leaves_no_partial_row(self, customer):
        before = User.objects.count()
        with pytest.raises(ConflictDomainError):
            services.register_customer(**registration_data(phone=customer.phone))
        assert User.objects.count() == before

    def test_registered_user_can_authenticate_immediately(self):
        data = registration_data()
        user = services.register_customer(**data)
        assert services.authenticate_user(email=data["email"], password=data["password"]).pk == user.pk


class TestRegisterServiceLevelValidation:
    @pytest.mark.parametrize(
        "password",
        [PASSWORD_TOO_SHORT, PASSWORD_COMMON, PASSWORD_ALL_NUMERIC],
        ids=["trop_court", "commun", "tout_numerique"],
    )
    def test_weak_password_is_rejected(self, password):
        before = User.objects.count()
        with pytest.raises(VALIDATION_ERRORS):
            services.register_customer(**registration_data(password=password))
        assert User.objects.count() == before

    @pytest.mark.parametrize(
        "phone", ["0102030405", "+2250102030405\n", "+225 01 02 03", "abc", ""]
    )
    def test_invalid_phone_is_rejected(self, phone):
        before = User.objects.count()
        with pytest.raises(VALIDATION_ERRORS):
            services.register_customer(**registration_data(phone=phone))
        assert User.objects.count() == before

    @pytest.mark.parametrize("email", ["pas-un-email", "a@", "", "a b@example.com"])
    def test_invalid_email_is_rejected(self, email):
        before = User.objects.count()
        with pytest.raises(VALIDATION_ERRORS):
            services.register_customer(**registration_data(email=email))
        assert User.objects.count() == before

    def test_empty_full_name_is_rejected(self):
        before = User.objects.count()
        with pytest.raises(VALIDATION_ERRORS):
            services.register_customer(**registration_data(full_name=""))
        assert User.objects.count() == before


# ==========================================================================
# authenticate_user
# ==========================================================================
class TestAuthenticateUser:
    def test_valid_credentials_return_the_user(self, customer):
        user = services.authenticate_user(email=customer.email, password=VALID_PASSWORD)
        assert user.pk == customer.pk

    def test_email_is_case_insensitive(self, customer):
        user = services.authenticate_user(email=customer.email.upper(), password=VALID_PASSWORD)
        assert user.pk == customer.pk

    def test_wrong_password(self, customer):
        with pytest.raises(AuthenticationDomainError) as exc:
            services.authenticate_user(email=customer.email, password="Mauvais!Mdp-123")
        assert_domain_error(exc, AuthenticationDomainError, CODE_INVALID_CREDENTIALS)

    def test_unknown_email(self, db):
        with pytest.raises(AuthenticationDomainError) as exc:
            services.authenticate_user(email="inconnu@example.com", password=VALID_PASSWORD)
        assert_domain_error(exc, AuthenticationDomainError, CODE_INVALID_CREDENTIALS)

    def test_unknown_email_and_wrong_password_are_indistinguishable(self, customer):
        with pytest.raises(AuthenticationDomainError) as wrong_pw:
            services.authenticate_user(email=customer.email, password="Mauvais!Mdp-123")
        with pytest.raises(AuthenticationDomainError) as unknown:
            services.authenticate_user(email="inconnu@example.com", password="Mauvais!Mdp-123")
        assert code_of(wrong_pw.value) == code_of(unknown.value)
        assert message_of(wrong_pw.value) == message_of(unknown.value)

    def test_disabled_account_with_correct_password(self, customer):
        customer.is_active = False
        customer.save()
        with pytest.raises(AuthenticationDomainError) as exc:
            services.authenticate_user(email=customer.email, password=VALID_PASSWORD)
        assert_domain_error(exc, AuthenticationDomainError, CODE_ACCOUNT_DISABLED)

    def test_disabled_account_with_wrong_password_does_not_reveal_status(self, customer):
        """Sans le bon mot de passe, on ne doit pas révéler que le compte est désactivé."""
        customer.is_active = False
        customer.save()
        with pytest.raises(AuthenticationDomainError) as exc:
            services.authenticate_user(email=customer.email, password="Mauvais!Mdp-123")
        assert_domain_error(exc, AuthenticationDomainError, CODE_INVALID_CREDENTIALS)

    def test_empty_password(self, customer):
        with pytest.raises(AuthenticationDomainError) as exc:
            services.authenticate_user(email=customer.email, password="")
        assert_domain_error(exc, AuthenticationDomainError, CODE_INVALID_CREDENTIALS)

    def test_account_without_usable_password_cannot_log_in(self, db):
        user = create_user(password=None)
        for attempt in ("", VALID_PASSWORD, "!", "None"):
            with pytest.raises(AuthenticationDomainError):
                services.authenticate_user(email=user.email, password=attempt)

    @pytest.mark.parametrize(
        "email",
        ["' OR '1'='1", "admin@example.com' --", "x@y.z\x00", "\x00", "a" * 10_000 + "@example.com"],
        ids=["sqli_or", "sqli_comment", "nul_suffix", "nul_seul", "tres_long"],
    )
    def test_hostile_emails_are_plain_invalid_credentials(self, db, email):
        with pytest.raises(AuthenticationDomainError) as exc:
            services.authenticate_user(email=email, password=VALID_PASSWORD)
        assert_domain_error(exc, AuthenticationDomainError, CODE_INVALID_CREDENTIALS)

    def test_arguments_are_keyword_only(self, customer):
        with pytest.raises(TypeError):
            services.authenticate_user(customer.email, VALID_PASSWORD)


# ==========================================================================
# update_profile
# ==========================================================================
def fresh(user):
    return User.objects.get(pk=user.pk)


class TestUpdateProfile:
    def test_full_name_only(self, customer):
        phone = customer.phone
        result = services.update_profile(user=customer, full_name="Nouveau Nom")
        assert result.pk == customer.pk
        assert (fresh(customer).full_name, fresh(customer).phone) == ("Nouveau Nom", phone)

    def test_phone_only(self, customer):
        name = customer.full_name
        services.update_profile(user=customer, phone="+2250700000001")
        assert (fresh(customer).full_name, fresh(customer).phone) == (name, "+2250700000001")

    def test_both_fields(self, customer):
        services.update_profile(user=customer, full_name="Autre Nom", phone="+2250700000002")
        stored = fresh(customer)
        assert (stored.full_name, stored.phone) == ("Autre Nom", "+2250700000002")

    def test_none_values_touch_nothing(self, customer):
        before = (customer.full_name, customer.phone)
        result = services.update_profile(user=customer)
        assert (result.full_name, result.phone) == before
        assert (fresh(customer).full_name, fresh(customer).phone) == before

    def test_returned_user_reflects_the_changes(self, customer):
        result = services.update_profile(user=customer, full_name="Reflet")
        assert result.full_name == "Reflet"

    def test_same_phone_as_own_is_accepted(self, customer):
        services.update_profile(user=customer, phone=customer.phone)
        assert fresh(customer).phone == customer.phone

    def test_phone_used_by_another_user_raises_conflict(self, customer, other_customer):
        with pytest.raises(ConflictDomainError) as exc:
            services.update_profile(user=customer, phone=other_customer.phone)
        assert_domain_error(exc, ConflictDomainError, CODE_PHONE_ALREADY_EXISTS)
        assert fresh(customer).phone == customer.phone

    def test_conflict_does_not_apply_the_other_field(self, customer, other_customer):
        """Atomicité : full_name ne doit pas être modifié si le phone échoue."""
        original = customer.full_name
        with pytest.raises(ConflictDomainError):
            services.update_profile(
                user=customer, full_name="Ne Doit Pas Passer", phone=other_customer.phone
            )
        assert fresh(customer).full_name == original

    def test_updated_at_moves_when_something_changes(self, customer):
        with freeze_time("2030-01-01 10:00:00"):
            services.update_profile(user=customer, full_name="Horodatage")
        assert fresh(customer).updated_at.year == 2030

    @pytest.mark.parametrize("forbidden", [{"email": "x@y.z"}, {"role": "ADMIN"}, {"is_staff": True}, {"password": "x"}])
    def test_only_profile_fields_are_accepted(self, customer, forbidden):
        with pytest.raises(TypeError):
            services.update_profile(user=customer, **forbidden)

    def test_other_users_are_never_modified(self, customer, other_customer):
        snapshot = (other_customer.full_name, other_customer.phone)
        services.update_profile(user=customer, full_name="Seulement Moi")
        assert (fresh(other_customer).full_name, fresh(other_customer).phone) == snapshot


class TestUpdateProfileServiceLevelValidation:
    def test_empty_full_name_is_rejected_and_none_is_not_the_same_thing(self, customer):
        original = customer.full_name
        with pytest.raises(VALIDATION_ERRORS):
            services.update_profile(user=customer, full_name="")
        assert fresh(customer).full_name == original

    @pytest.mark.parametrize(
        "phone",
        ["", "0102030405", "+2250102030405\n", "+225 01 02 03", "+" + "".join(chr(0x0660 + int(d)) for d in "2250102030405")],
        ids=["vide", "local", "newline", "espaces", "chiffres_arabes"],
    )
    def test_invalid_phone_is_rejected_and_not_saved(self, customer, phone):
        original = customer.phone
        with pytest.raises(VALIDATION_ERRORS):
            services.update_profile(user=customer, phone=phone)
        assert fresh(customer).phone == original
