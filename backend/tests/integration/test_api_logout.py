"""POST /api/v1/auth/logout/"""
import pytest
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from apps.accounts import services
from tests.api_helpers import (
    assert_cookie_deleted,
    bearer,
    is_blacklisted,
    login,
    morsel,
    set_cookie,
    tamper_signature,
)
from tests.constants import CODE_REFRESH_TOKEN_INVALID, URL_LOGOUT, URL_ME, URL_REFRESH
from tests.helpers import assert_unified_error

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def tokens(customer):
    return services.issue_auth_tokens(user=customer)


@pytest.fixture
def session(api_client, tokens):
    set_cookie(api_client, tokens.refresh_token)
    return api_client


# ==========================================================================
# Logout nominal
# ==========================================================================
class TestLogoutSuccess:
    def test_returns_204_with_empty_body(self, session):
        r = session.post(URL_LOGOUT)
        assert r.status_code == 204
        assert r.content == b""

    def test_refresh_token_is_blacklisted(self, session, tokens):
        session.post(URL_LOGOUT)
        assert is_blacklisted(tokens.refresh_token)

    def test_cookie_is_deleted(self, session):
        assert_cookie_deleted(session.post(URL_LOGOUT))

    def test_deletion_cookie_matches_creation_attributes(self, api_client, customer):
        """Sinon le navigateur ne supprime pas réellement le cookie."""
        created = morsel(login(api_client, customer))
        deleted = api_client.post(URL_LOGOUT)
        assert_cookie_deleted(deleted, like=created)

    def test_refresh_is_impossible_after_logout(self, api_client, tokens):
        set_cookie(api_client, tokens.refresh_token)
        api_client.post(URL_LOGOUT)
        set_cookie(api_client, tokens.refresh_token)  # cookie rejoué
        assert_unified_error(api_client.post(URL_REFRESH), 401, CODE_REFRESH_TOKEN_INVALID)

    def test_full_cycle_login_logout(self, api_client, customer):
        login(api_client, customer)
        assert api_client.post(URL_LOGOUT).status_code == 204
        assert api_client.post(URL_REFRESH).status_code == 401

    def test_other_sessions_of_the_same_user_stay_valid(self, customer):
        from rest_framework.test import APIClient

        a, b = APIClient(), APIClient()
        login(a, customer)
        login(b, customer)
        assert a.post(URL_LOGOUT).status_code == 204
        assert b.post(URL_REFRESH).status_code == 200

    def test_access_token_remains_valid_until_expiry_known_behaviour(self, session, tokens):
        """Comportement connu et documenté : seul le refresh est révoqué."""
        session.post(URL_LOGOUT)
        client = type(session)()
        bearer(client, tokens.access_token)
        assert client.get(URL_ME).status_code == 200


# ==========================================================================
# Idempotence (hypothèse n°4)
# ==========================================================================
class TestLogoutIsIdempotent:
    def test_without_cookie(self, api_client, db):
        r = api_client.post(URL_LOGOUT)
        assert r.status_code == 204

    @pytest.mark.parametrize("value", ["garbage", "a.b.c", "x" * 5000, ""], ids=["garbage", "a.b.c", "tres_long", "vide"])
    def test_with_garbage_cookie(self, api_client, db, value):
        set_cookie(api_client, value)
        assert api_client.post(URL_LOGOUT).status_code == 204

    def test_with_forged_cookie_nothing_is_blacklisted(self, api_client, tokens):
        before = BlacklistedToken.objects.count()
        set_cookie(api_client, tamper_signature(tokens.refresh_token))
        assert api_client.post(URL_LOGOUT).status_code == 204
        assert BlacklistedToken.objects.count() == before

    def test_with_access_token_in_cookie_nothing_is_blacklisted(self, api_client, tokens):
        before = BlacklistedToken.objects.count()
        set_cookie(api_client, tokens.access_token)
        assert api_client.post(URL_LOGOUT).status_code == 204
        assert BlacklistedToken.objects.count() == before

    def test_already_revoked_token(self, api_client, tokens):
        set_cookie(api_client, tokens.refresh_token)
        assert api_client.post(URL_LOGOUT).status_code == 204
        set_cookie(api_client, tokens.refresh_token)
        assert api_client.post(URL_LOGOUT).status_code == 204

    def test_deletion_cookie_is_sent_even_without_valid_session(self, api_client, db):
        set_cookie(api_client, "garbage")
        assert_cookie_deleted(api_client.post(URL_LOGOUT))

    def test_logout_of_a_disabled_user_still_works(self, session, customer):
        customer.is_active = False
        customer.save()
        assert session.post(URL_LOGOUT).status_code == 204

    def test_logout_of_a_deleted_user_does_not_crash(self, session, customer):
        customer.delete()
        assert session.post(URL_LOGOUT).status_code == 204


# ==========================================================================
# Méthodes / accès
# ==========================================================================
class TestLogoutAccess:
    @pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
    def test_other_methods_are_405_and_do_not_revoke(self, session, tokens, method):
        assert_unified_error(getattr(session, method)(URL_LOGOUT), 405)
        assert not is_blacklisted(tokens.refresh_token)

    def test_garbage_bearer_header_does_not_block_logout(self, session):
        bearer(session, "ceci.n.est.pas.un.jwt")
        assert session.post(URL_LOGOUT).status_code == 204

    def test_logout_does_not_set_a_new_valid_cookie(self, session, tokens):
        m = morsel(session.post(URL_LOGOUT))
        assert m is not None and m.value == ""
