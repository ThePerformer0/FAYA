"""POST /api/v1/auth/login/"""
import json

import pytest
from django.utils import timezone
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import AccessToken
from datetime import timedelta

from apps.accounts.models import UserRole
from tests.api_helpers import assert_refresh_cookie, cookie_value, morsel
from tests.constants import (
    CODE_ACCOUNT_DISABLED,
    CODE_INVALID_CREDENTIALS,
    CODE_VALIDATION,
    URL_LOGIN,
    URL_ME,
    VALID_PASSWORD,
)
from tests.factories import make_suspension
from tests.helpers import assert_unified_error, create_user

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

FORBIDDEN_USER_KEYS = {"password", "password_hash", "refresh_token", "refresh", "is_staff", "is_superuser"}


def do_login(client, email, password=VALID_PASSWORD):
    return client.post(URL_LOGIN, {"email": email, "password": password}, format="json")


# ==========================================================================
# Succès
# ==========================================================================
class TestLoginSuccess:
    def test_returns_200_with_exactly_access_token_and_user(self, api_client, customer):
        r = do_login(api_client, customer.email)
        assert r.status_code == 200, r.content
        assert set(r.json()) == {"access_token", "user"}

    def test_user_payload(self, api_client, customer):
        user = do_login(api_client, customer.email).json()["user"]
        assert user["id"] == str(customer.pk)
        assert user["email"] == customer.email
        assert user["role"] == UserRole.CUSTOMER
        assert not (FORBIDDEN_USER_KEYS & set(user))

    @pytest.mark.parametrize("role", [UserRole.CUSTOMER, UserRole.DEPOT_MANAGER, UserRole.ADMIN])
    def test_every_role_can_log_in(self, api_client, role):
        user = create_user(role=role)
        r = do_login(api_client, user.email)
        assert r.status_code == 200
        assert r.json()["user"]["role"] == role

    def test_refresh_cookie_is_set_with_secure_attributes(self, api_client, customer):
        assert_refresh_cookie(do_login(api_client, customer.email), customer)

    def test_refresh_token_never_appears_in_the_body(self, api_client, customer):
        r = do_login(api_client, customer.email)
        assert cookie_value(r) not in r.content.decode()

    def test_password_and_hash_never_returned(self, api_client, customer):
        text = do_login(api_client, customer.email).content.decode()
        assert VALID_PASSWORD not in text and customer.password not in text

    def test_access_token_is_valid_and_works_on_me(self, api_client, customer):
        token = do_login(api_client, customer.email).json()["access_token"]
        assert AccessToken(token)[jwt_settings.USER_ID_CLAIM] == str(customer.pk)
        api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        assert api_client.get(URL_ME).status_code == 200

    def test_each_login_issues_a_new_refresh_token(self, api_client, customer):
        first = cookie_value(do_login(api_client, customer.email))
        second = cookie_value(do_login(api_client, customer.email))
        assert first != second

    def test_email_is_case_insensitive(self, api_client, customer):
        assert do_login(api_client, customer.email.upper()).status_code == 200

    def test_surrounding_whitespace_in_email_is_tolerated(self, api_client, customer):
        assert do_login(api_client, f"  {customer.email}  ").status_code == 200

    def test_suspended_customer_can_still_log_in(self, api_client, customer):
        """Hypothèse n°1 : la suspension bloque la réservation, pas la connexion."""
        now = timezone.now()
        make_suspension(customer, starts_at=now - timedelta(days=1), ends_at=now + timedelta(days=6))
        assert do_login(api_client, customer.email).status_code == 200


# ==========================================================================
# Échecs d'authentification
# ==========================================================================
class TestLoginFailures:
    def test_wrong_password(self, api_client, customer):
        r = do_login(api_client, customer.email, "Mauvais!Mdp-123")
        assert_unified_error(r, 401, CODE_INVALID_CREDENTIALS)

    def test_unknown_email(self, api_client, db):
        r = do_login(api_client, "inconnu@example.com")
        assert_unified_error(r, 401, CODE_INVALID_CREDENTIALS)

    def test_unknown_email_and_wrong_password_are_strictly_identical(self, api_client, customer):
        wrong = do_login(api_client, customer.email, "Mauvais!Mdp-123")
        unknown = do_login(api_client, "inconnu@example.com", "Mauvais!Mdp-123")
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()

    def test_disabled_account_with_correct_password(self, api_client, customer):
        customer.is_active = False
        customer.save()
        assert_unified_error(do_login(api_client, customer.email), 401, CODE_ACCOUNT_DISABLED)

    def test_disabled_account_with_wrong_password_looks_like_any_failure(self, api_client, customer):
        customer.is_active = False
        customer.save()
        r = do_login(api_client, customer.email, "Mauvais!Mdp-123")
        assert_unified_error(r, 401, CODE_INVALID_CREDENTIALS)

    def test_failure_sets_no_refresh_cookie(self, api_client, customer):
        r = do_login(api_client, customer.email, "Mauvais!Mdp-123")
        m = morsel(r)
        assert m is None or m.value == ""

    def test_failure_body_does_not_echo_credentials(self, api_client, customer):
        r = do_login(api_client, customer.email, "Mauvais!Mdp-123")
        text = r.content.decode()
        assert "Mauvais!Mdp-123" not in text and customer.email not in text

    def test_deleted_user_cannot_log_in(self, api_client, customer):
        email = customer.email
        customer.delete()
        assert_unified_error(do_login(api_client, email), 401, CODE_INVALID_CREDENTIALS)


# ==========================================================================
# Validation du corps
# ==========================================================================
class TestLoginValidation:
    @pytest.mark.parametrize("field", ["email", "password"])
    def test_missing_field(self, api_client, field):
        data = {"email": "a@example.com", "password": VALID_PASSWORD}
        data.pop(field)
        body = assert_unified_error(api_client.post(URL_LOGIN, data, format="json"), 400, CODE_VALIDATION)
        assert field in json.dumps(body["details"])

    @pytest.mark.parametrize("field", ["email", "password"])
    @pytest.mark.parametrize("bad", [None, "", [], {}, True], ids=["null", "vide", "liste", "objet", "bool"])
    def test_null_empty_or_wrongly_typed_field(self, api_client, field, bad):
        data = {"email": "a@example.com", "password": VALID_PASSWORD, field: bad}
        assert_unified_error(api_client.post(URL_LOGIN, data, format="json"), 400, CODE_VALIDATION)

    def test_invalid_json(self, api_client):
        r = api_client.post(URL_LOGIN, data="{pas du json", content_type="application/json")
        assert_unified_error(r, 400)

    def test_unsupported_media_type(self, api_client):
        r = api_client.post(URL_LOGIN, data="email=a", content_type="text/plain")
        assert_unified_error(r, 415)

    @pytest.mark.parametrize(
        "email",
        ["' OR '1'='1", "admin@example.com' --", "x@example.com\x00", "a" * 10_000 + "@example.com"],
        ids=["sqli_or", "sqli_commentaire", "nul", "tres_long"],
    )
    def test_hostile_email_is_a_client_error_not_a_500(self, api_client, email):
        r = do_login(api_client, email)
        assert r.status_code in (400, 401)
        assert_unified_error(r)

    @pytest.mark.parametrize("password", ["\x00", "a" * 100_000], ids=["nul", "enorme"])
    def test_hostile_password_is_a_client_error_not_a_500(self, api_client, customer, password):
        r = do_login(api_client, customer.email, password)
        assert r.status_code in (400, 401)
        assert_unified_error(r)


# ==========================================================================
# Endpoint public
# ==========================================================================
class TestLoginIsPublic:
    @pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
    def test_other_methods_are_405(self, api_client, method):
        assert_unified_error(getattr(api_client, method)(URL_LOGIN), 405)

    def test_garbage_bearer_header_does_not_block_login(self, api_client, customer):
        """Un front avec un access token périmé doit pouvoir se reconnecter."""
        api_client.credentials(HTTP_AUTHORIZATION="Bearer ceci.n.est.pas.un.jwt")
        assert do_login(api_client, customer.email).status_code == 200

    def test_login_while_already_logged_in_replaces_the_session(self, api_client, customer):
        first = cookie_value(do_login(api_client, customer.email))
        second = do_login(api_client, customer.email)
        assert cookie_value(second) and cookie_value(second) != first
