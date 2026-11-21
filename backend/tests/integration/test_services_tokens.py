"""Services de jetons : issue_auth_tokens, rotate_refresh_token, revoke_refresh_token.

Les tests de forge (signature, payload, alg=none, mauvaise clé) travaillent au
niveau service ; ils seront rejoués via le cookie HTTP dans le lot sécurité.
"""
import base64
import json
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from freezegun import freeze_time
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts import services
from apps.core.exceptions import AuthenticationDomainError
from tests.constants import (
    CODE_ACCOUNT_DISABLED,
    CODE_REFRESH_TOKEN_INVALID,
    CODE_REFRESH_TOKEN_MISSING,
)
from tests.domain_asserts import assert_domain_error, code_of

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

INVALID_OR_MISSING = {CODE_REFRESH_TOKEN_INVALID, CODE_REFRESH_TOKEN_MISSING}


# --------------------------------------------------------------------------
# Utilitaires
# --------------------------------------------------------------------------
def raw_payload(token):
    return jwt.decode(token, options={"verify_signature": False})


def jti_of(token):
    return raw_payload(token)["jti"]


def is_blacklisted(token):
    return BlacklistedToken.objects.filter(token__jti=jti_of(token)).exists()


def tamper_signature(token):
    header, payload, sig = token.split(".")
    sig = ("A" if sig[0] != "A" else "B") + sig[1:]
    return f"{header}.{payload}.{sig}"


def forge_payload(token, **claims):
    header, payload, sig = token.split(".")
    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    data.update(claims)
    new = base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()
    return f"{header}.{new}.{sig}"


def revoke_outcome(raw):
    """Revoke est tolérant : retourne None ou lève une AuthenticationDomainError. Rien d'autre."""
    try:
        result = services.revoke_refresh_token(raw_refresh_token=raw)
    except AuthenticationDomainError:
        return "refused"
    assert result is None
    return "ok"


@pytest.fixture
def tokens(customer):
    return services.issue_auth_tokens(user=customer)


# ==========================================================================
# issue_auth_tokens
# ==========================================================================
class TestIssueAuthTokens:
    def test_returns_two_distinct_non_empty_strings(self, tokens):
        assert isinstance(tokens.access_token, str) and tokens.access_token
        assert isinstance(tokens.refresh_token, str) and tokens.refresh_token
        assert tokens.access_token != tokens.refresh_token

    def test_access_token_identifies_the_user(self, tokens, customer):
        access = AccessToken(tokens.access_token)
        assert access[jwt_settings.USER_ID_CLAIM] == str(customer.pk)
        assert access["token_type"] == "access"

    def test_refresh_token_has_refresh_type_and_same_user(self, tokens, customer):
        payload = raw_payload(tokens.refresh_token)
        assert payload["token_type"] == "refresh"
        assert payload[jwt_settings.USER_ID_CLAIM] == str(customer.pk)

    def test_refresh_token_is_tracked_in_outstanding_tokens(self, tokens, customer):
        outstanding = OutstandingToken.objects.get(jti=jti_of(tokens.refresh_token))
        assert outstanding.user_id == customer.pk

    def test_access_token_is_short_lived_and_shorter_than_refresh(self, tokens):
        access = raw_payload(tokens.access_token)
        refresh = raw_payload(tokens.refresh_token)
        access_ttl = access["exp"] - access["iat"]
        refresh_ttl = refresh["exp"] - refresh["iat"]
        assert access_ttl <= 30 * 60, f"access token trop long : {access_ttl}s"
        assert refresh_ttl > access_ttl

    def test_two_issuances_give_different_tokens(self, customer):
        a = services.issue_auth_tokens(user=customer)
        b = services.issue_auth_tokens(user=customer)
        assert jti_of(a.refresh_token) != jti_of(b.refresh_token)
        assert jti_of(a.access_token) != jti_of(b.access_token)

    def test_tokens_do_not_embed_secrets(self, tokens):
        for raw in (tokens.access_token, tokens.refresh_token):
            blob = json.dumps(raw_payload(raw)).lower()
            assert "password" not in blob and "argon2" not in blob and "md5$" not in blob

    def test_argument_is_keyword_only(self, customer):
        with pytest.raises(TypeError):
            services.issue_auth_tokens(customer)


# ==========================================================================
# rotate_refresh_token
# ==========================================================================
class TestRotateRefreshToken:
    def test_returns_new_tokens_and_blacklists_the_old_one(self, tokens):
        new = services.rotate_refresh_token(raw_refresh_token=tokens.refresh_token)
        assert new.refresh_token != tokens.refresh_token
        assert new.access_token != tokens.access_token
        assert is_blacklisted(tokens.refresh_token)
        assert not is_blacklisted(new.refresh_token)

    def test_new_access_token_belongs_to_the_same_user(self, tokens, customer):
        new = services.rotate_refresh_token(raw_refresh_token=tokens.refresh_token)
        assert AccessToken(new.access_token)[jwt_settings.USER_ID_CLAIM] == str(customer.pk)

    def test_old_token_cannot_be_reused(self, tokens):
        services.rotate_refresh_token(raw_refresh_token=tokens.refresh_token)
        with pytest.raises(AuthenticationDomainError) as exc:
            services.rotate_refresh_token(raw_refresh_token=tokens.refresh_token)
        assert_domain_error(exc, AuthenticationDomainError, CODE_REFRESH_TOKEN_INVALID)

    def test_rotation_can_be_chained(self, tokens):
        second = services.rotate_refresh_token(raw_refresh_token=tokens.refresh_token)
        third = services.rotate_refresh_token(raw_refresh_token=second.refresh_token)
        assert third.refresh_token not in (tokens.refresh_token, second.refresh_token)

    def test_rotating_one_session_does_not_affect_another(self, customer):
        session_a = services.issue_auth_tokens(user=customer)
        session_b = services.issue_auth_tokens(user=customer)
        services.rotate_refresh_token(raw_refresh_token=session_a.refresh_token)
        assert not is_blacklisted(session_b.refresh_token)
        services.rotate_refresh_token(raw_refresh_token=session_b.refresh_token)

    @pytest.mark.parametrize(
        "raw",
        ["", "garbage", "a.b.c", "x" * 5000, "null", "Bearer abc", " ", "\x00"],
        ids=["vide", "garbage", "a.b.c", "tres_long", "null", "bearer", "espace", "nul"],
    )
    def test_garbage_is_a_domain_error_never_a_raw_exception(self, db, raw):
        with pytest.raises(AuthenticationDomainError) as exc:
            services.rotate_refresh_token(raw_refresh_token=raw)
        assert code_of(exc.value) in INVALID_OR_MISSING

    def test_none_is_a_domain_error(self, db):
        with pytest.raises(AuthenticationDomainError) as exc:
            services.rotate_refresh_token(raw_refresh_token=None)
        assert code_of(exc.value) in INVALID_OR_MISSING

    def test_access_token_is_not_accepted_as_refresh_token(self, tokens):
        with pytest.raises(AuthenticationDomainError) as exc:
            services.rotate_refresh_token(raw_refresh_token=tokens.access_token)
        assert_domain_error(exc, AuthenticationDomainError, CODE_REFRESH_TOKEN_INVALID)

    def test_tampered_signature_is_rejected(self, tokens):
        with pytest.raises(AuthenticationDomainError) as exc:
            services.rotate_refresh_token(raw_refresh_token=tamper_signature(tokens.refresh_token))
        assert_domain_error(exc, AuthenticationDomainError, CODE_REFRESH_TOKEN_INVALID)

    def test_forged_user_id_is_rejected(self, tokens, other_customer):
        forged = forge_payload(tokens.refresh_token, **{jwt_settings.USER_ID_CLAIM: str(other_customer.pk)})
        with pytest.raises(AuthenticationDomainError) as exc:
            services.rotate_refresh_token(raw_refresh_token=forged)
        assert_domain_error(exc, AuthenticationDomainError, CODE_REFRESH_TOKEN_INVALID)

    def test_alg_none_token_is_rejected(self, tokens):
        forged = jwt.encode(raw_payload(tokens.refresh_token), key=None, algorithm="none")
        with pytest.raises(AuthenticationDomainError) as exc:
            services.rotate_refresh_token(raw_refresh_token=forged)
        assert_domain_error(exc, AuthenticationDomainError, CODE_REFRESH_TOKEN_INVALID)

    def test_token_signed_with_another_key_is_rejected(self, tokens):
        forged = jwt.encode(
            raw_payload(tokens.refresh_token), key="x" * 64, algorithm="HS256"
        )
        with pytest.raises(AuthenticationDomainError) as exc:
            services.rotate_refresh_token(raw_refresh_token=forged)
        assert_domain_error(exc, AuthenticationDomainError, CODE_REFRESH_TOKEN_INVALID)

    def test_expired_refresh_token_is_rejected(self, tokens):
        later = datetime.now(timezone.utc) + jwt_settings.REFRESH_TOKEN_LIFETIME + timedelta(minutes=1)
        with freeze_time(later):
            with pytest.raises(AuthenticationDomainError) as exc:
                services.rotate_refresh_token(raw_refresh_token=tokens.refresh_token)
        assert_domain_error(exc, AuthenticationDomainError, CODE_REFRESH_TOKEN_INVALID)

    def test_disabled_user_cannot_rotate_and_nothing_is_issued(self, tokens, customer):
        customer.is_active = False
        customer.save()
        before = OutstandingToken.objects.count()
        with pytest.raises(AuthenticationDomainError) as exc:
            services.rotate_refresh_token(raw_refresh_token=tokens.refresh_token)
        assert code_of(exc.value) in {CODE_ACCOUNT_DISABLED, CODE_REFRESH_TOKEN_INVALID}
        assert OutstandingToken.objects.count() == before

    def test_deleted_user_cannot_rotate(self, tokens, customer):
        customer.delete()
        with pytest.raises(AuthenticationDomainError):
            services.rotate_refresh_token(raw_refresh_token=tokens.refresh_token)

    def test_argument_is_keyword_only(self, tokens):
        with pytest.raises(TypeError):
            services.rotate_refresh_token(tokens.refresh_token)


class TestRotationDesirableHardening:
    """Souhaitable (non exigé par la spec) : détection de vol par réutilisation."""

    def test_replaying_a_rotated_token_revokes_the_whole_family(self, tokens):
        new = services.rotate_refresh_token(raw_refresh_token=tokens.refresh_token)
        with pytest.raises(AuthenticationDomainError):
            services.rotate_refresh_token(raw_refresh_token=tokens.refresh_token)  # rejeu
        with pytest.raises(AuthenticationDomainError):
            services.rotate_refresh_token(raw_refresh_token=new.refresh_token)


# ==========================================================================
# revoke_refresh_token
# ==========================================================================
class TestRevokeRefreshToken:
    def test_revokes_the_token_and_returns_none(self, tokens):
        assert services.revoke_refresh_token(raw_refresh_token=tokens.refresh_token) is None
        assert is_blacklisted(tokens.refresh_token)

    def test_revoked_token_cannot_be_rotated(self, tokens):
        services.revoke_refresh_token(raw_refresh_token=tokens.refresh_token)
        with pytest.raises(AuthenticationDomainError) as exc:
            services.rotate_refresh_token(raw_refresh_token=tokens.refresh_token)
        assert_domain_error(exc, AuthenticationDomainError, CODE_REFRESH_TOKEN_INVALID)

    def test_revoking_twice_is_idempotent_or_cleanly_refused(self, tokens):
        assert revoke_outcome(tokens.refresh_token) == "ok"
        assert revoke_outcome(tokens.refresh_token) in {"ok", "refused"}
        assert is_blacklisted(tokens.refresh_token)

    def test_other_sessions_stay_valid(self, customer):
        a = services.issue_auth_tokens(user=customer)
        b = services.issue_auth_tokens(user=customer)
        services.revoke_refresh_token(raw_refresh_token=a.refresh_token)
        assert not is_blacklisted(b.refresh_token)
        services.rotate_refresh_token(raw_refresh_token=b.refresh_token)

    @pytest.mark.parametrize("raw", ["", "garbage", "a.b.c", "x" * 5000, "\x00"],
                             ids=["vide", "garbage", "a.b.c", "tres_long", "nul"])
    def test_garbage_never_raises_a_raw_exception(self, db, raw):
        assert revoke_outcome(raw) in {"ok", "refused"}

    def test_none_never_raises_a_raw_exception(self, db):
        assert revoke_outcome(None) in {"ok", "refused"}

    def test_access_token_passed_instead_is_not_blacklisted(self, tokens):
        before = BlacklistedToken.objects.count()
        assert revoke_outcome(tokens.access_token) in {"ok", "refused"}
        assert BlacklistedToken.objects.count() == before

    def test_argument_is_keyword_only(self, tokens):
        with pytest.raises(TypeError):
            services.revoke_refresh_token(tokens.refresh_token)
