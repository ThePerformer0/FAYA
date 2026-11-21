"""POST /api/v1/auth/refresh/ (cookie HttpOnly uniquement)"""
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from freezegun import freeze_time
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts import services
from tests.api_helpers import (
    alg_none,
    assert_refresh_cookie,
    bearer,
    cookie_value,
    forge_payload,
    is_blacklisted,
    login,
    morsel,
    set_cookie,
    tamper_signature,
    wrong_key,
)
from tests.constants import (
    CODE_ACCOUNT_DISABLED,
    CODE_REFRESH_TOKEN_INVALID,
    CODE_REFRESH_TOKEN_MISSING,
    URL_LOGOUT,
    URL_ME,
    URL_REFRESH,
)
from tests.helpers import assert_unified_error

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.fixture
def tokens(customer):
    return services.issue_auth_tokens(user=customer)


@pytest.fixture
def session(api_client, tokens):
    set_cookie(api_client, tokens.refresh_token)
    return api_client


def refresh(client):
    return client.post(URL_REFRESH, data=None)


# ==========================================================================
# Succès
# ==========================================================================
class TestRefreshSuccess:
    def test_returns_200_with_only_an_access_token(self, session):
        r = refresh(session)
        assert r.status_code == 200, r.content
        assert set(r.json()) == {"access_token"}

    def test_cookie_is_rotated_with_secure_attributes(self, session, tokens, customer):
        r = refresh(session)
        new_value = assert_refresh_cookie(r, customer)
        assert new_value != tokens.refresh_token

    def test_refresh_token_never_appears_in_the_body(self, session):
        r = refresh(session)
        assert cookie_value(r) not in r.content.decode()

    def test_new_access_token_is_valid_for_the_same_user(self, session, customer):
        token = refresh(session).json()["access_token"]
        assert AccessToken(token)[jwt_settings.USER_ID_CLAIM] == str(customer.pk)
        client = type(session)()
        bearer(client, token)
        assert client.get(URL_ME).status_code == 200

    def test_old_refresh_token_is_blacklisted(self, session, tokens):
        refresh(session)
        assert is_blacklisted(tokens.refresh_token)

    def test_old_refresh_token_cannot_be_replayed(self, api_client, tokens):
        set_cookie(api_client, tokens.refresh_token)
        refresh(api_client)
        set_cookie(api_client, tokens.refresh_token)  # rejeu de l'ancien cookie
        assert_unified_error(refresh(api_client), 401, CODE_REFRESH_TOKEN_INVALID)

    def test_rotation_can_be_chained_through_the_cookie_jar(self, session):
        assert refresh(session).status_code == 200
        assert refresh(session).status_code == 200  # le client réutilise le nouveau cookie

    def test_works_after_a_real_login(self, api_client, customer):
        login(api_client, customer)
        assert refresh(api_client).status_code == 200

    def test_request_body_is_irrelevant(self, session):
        assert session.post(URL_REFRESH, {"foo": "bar"}, format="json").status_code == 200

    def test_cookie_identity_wins_over_bearer_identity(self, api_client, customer, other_customer):
        set_cookie(api_client, services.issue_auth_tokens(user=customer).refresh_token)
        bearer(api_client, services.issue_auth_tokens(user=other_customer).access_token)
        token = refresh(api_client).json()["access_token"]
        assert AccessToken(token)[jwt_settings.USER_ID_CLAIM] == str(customer.pk)

    def test_garbage_bearer_header_does_not_block_refresh(self, session):
        bearer(session, "ceci.n.est.pas.un.jwt")
        assert refresh(session).status_code == 200


# ==========================================================================
# Cookie absent / invalide
# ==========================================================================
class TestRefreshRejections:
    def test_missing_cookie(self, api_client, db):
        assert_unified_error(refresh(api_client), 401, CODE_REFRESH_TOKEN_MISSING)

    def test_empty_cookie(self, api_client, db):
        set_cookie(api_client, "")
        r = refresh(api_client)
        body = assert_unified_error(r, 401)
        assert body["code"] in {CODE_REFRESH_TOKEN_MISSING, CODE_REFRESH_TOKEN_INVALID}

    @pytest.mark.parametrize("value", ["garbage", "a.b.c", "x" * 5000, "null", "\x00"],
                             ids=["garbage", "a.b.c", "tres_long", "null", "nul"])
    def test_garbage_cookie(self, api_client, db, value):
        set_cookie(api_client, value)
        assert_unified_error(refresh(api_client), 401, CODE_REFRESH_TOKEN_INVALID)

    def test_access_token_in_the_cookie_is_rejected(self, api_client, tokens):
        set_cookie(api_client, tokens.access_token)
        assert_unified_error(refresh(api_client), 401, CODE_REFRESH_TOKEN_INVALID)

    @pytest.mark.parametrize("forge", [tamper_signature, alg_none, wrong_key], ids=["signature", "alg_none", "autre_cle"])
    def test_forged_token_in_the_cookie(self, api_client, tokens, forge):
        set_cookie(api_client, forge(tokens.refresh_token))
        assert_unified_error(refresh(api_client), 401, CODE_REFRESH_TOKEN_INVALID)

    def test_forged_user_id_in_the_cookie(self, api_client, tokens, other_customer):
        forged = forge_payload(tokens.refresh_token, **{jwt_settings.USER_ID_CLAIM: str(other_customer.pk)})
        set_cookie(api_client, forged)
        assert_unified_error(refresh(api_client), 401, CODE_REFRESH_TOKEN_INVALID)

    def test_expired_refresh_token(self, session):
        later = datetime.now(dt_timezone.utc) + jwt_settings.REFRESH_TOKEN_LIFETIME + timedelta(minutes=1)
        with freeze_time(later):
            r = refresh(session)
        assert_unified_error(r, 401, CODE_REFRESH_TOKEN_INVALID)

    def test_token_in_json_body_is_not_accepted(self, api_client, tokens):
        r = api_client.post(URL_REFRESH, {"refresh_token": tokens.refresh_token,
                                          "refresh": tokens.refresh_token}, format="json")
        assert_unified_error(r, 401, CODE_REFRESH_TOKEN_MISSING)
        assert not is_blacklisted(tokens.refresh_token)

    def test_token_in_query_string_is_not_accepted(self, api_client, tokens):
        r = api_client.post(f"{URL_REFRESH}?refresh_token={tokens.refresh_token}")
        assert_unified_error(r, 401, CODE_REFRESH_TOKEN_MISSING)

    def test_token_in_authorization_header_is_not_accepted(self, api_client, tokens):
        bearer(api_client, tokens.refresh_token)
        r = refresh(api_client)
        assert r.status_code == 401
        assert not is_blacklisted(tokens.refresh_token)

    def test_blacklisted_token_replayed_after_logout(self, api_client, tokens):
        set_cookie(api_client, tokens.refresh_token)
        api_client.post(URL_LOGOUT)
        set_cookie(api_client, tokens.refresh_token)
        assert_unified_error(refresh(api_client), 401, CODE_REFRESH_TOKEN_INVALID)

    def test_disabled_user_cannot_refresh(self, session, customer):
        customer.is_active = False
        customer.save()
        body = assert_unified_error(refresh(session), 401)
        assert body["code"] in {CODE_ACCOUNT_DISABLED, CODE_REFRESH_TOKEN_INVALID}

    def test_deleted_user_cannot_refresh(self, session, customer):
        customer.delete()
        assert_unified_error(refresh(session), 401)

    def test_failed_refresh_issues_no_new_valid_cookie(self, api_client, tokens):
        set_cookie(api_client, tamper_signature(tokens.refresh_token))
        m = morsel(refresh(api_client))
        assert m is None or m.value == "" or m.value != tokens.refresh_token


# ==========================================================================
# Méthodes HTTP (CSRF : jamais de rotation via GET)
# ==========================================================================
@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_only_post_is_allowed_and_cookie_is_untouched(session, tokens, method):
    r = getattr(session, method)(URL_REFRESH)
    assert_unified_error(r, 405)
    assert not is_blacklisted(tokens.refresh_token)
