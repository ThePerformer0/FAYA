"""Rotation et révocation de refresh tokens sous concurrence."""
import pytest
from functools import partial
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from apps.accounts import services
from apps.core.exceptions import AuthenticationDomainError
from tests.api_helpers import set_cookie
from tests.concurrency_helpers import run_concurrently, split
from tests.constants import CODE_REFRESH_TOKEN_INVALID, URL_LOGOUT, URL_REFRESH
from tests.domain_asserts import code_of
from tests.helpers import create_user

pytestmark = [pytest.mark.concurrency, pytest.mark.django_db(transaction=True)]

THREADS = 6


@pytest.mark.parametrize("round_", range(3))
class TestConcurrentRotation:
    def test_service_same_token_rotates_exactly_once(self, round_):
        user = create_user()
        tokens = services.issue_auth_tokens(user=user)
        rotate = partial(services.rotate_refresh_token, raw_refresh_token=tokens.refresh_token)
        oks, errs = split(run_concurrently([rotate] * THREADS))
        assert len(oks) == 1, (
            f"{len(oks)} rotations réussies avec le MÊME refresh token : "
            "double rotation (course sur la blacklist), il faut verrouiller la ligne OutstandingToken")
        for e in errs:
            assert isinstance(e, AuthenticationDomainError), f"erreur brute : {e!r}"
            assert code_of(e) == CODE_REFRESH_TOKEN_INVALID
        assert OutstandingToken.objects.filter(user=user).count() == 2  # initial + 1 nouveau
        assert BlacklistedToken.objects.count() in {1, 2}  # 2 si détection de rejeu famille déclenchée

    def test_api_same_cookie_one_200_rest_401(self, round_):
        user = create_user()
        refresh_token = services.issue_auth_tokens(user=user).refresh_token

        def call():
            client = APIClient()
            client.raise_request_exception = False
            set_cookie(client, refresh_token)
            return client.post(URL_REFRESH)

        oks, errs = split(run_concurrently([call] * THREADS))
        assert not errs, errs
        statuses = sorted(r.status_code for r in oks)
        assert statuses.count(200) == 1, f"statuts : {statuses}"
        assert set(statuses) <= {200, 401}


def test_concurrent_logout_with_same_cookie_is_idempotent():
    user = create_user()
    refresh_token = services.issue_auth_tokens(user=user).refresh_token

    def call():
        client = APIClient()
        client.raise_request_exception = False
        set_cookie(client, refresh_token)
        return client.post(URL_LOGOUT)

    oks, errs = split(run_concurrently([call] * THREADS))
    assert not errs, errs
    assert {r.status_code for r in oks} == {204}
    assert BlacklistedToken.objects.count() == 1


def test_concurrent_revoke_service_never_raises_raw_errors():
    user = create_user()
    refresh_token = services.issue_auth_tokens(user=user).refresh_token
    revoke = partial(services.revoke_refresh_token, raw_refresh_token=refresh_token)
    oks, errs = split(run_concurrently([revoke] * THREADS))
    assert all(isinstance(e, AuthenticationDomainError) for e in errs), errs
    assert BlacklistedToken.objects.count() == 1


def test_rotation_of_different_sessions_in_parallel_all_succeed():
    user = create_user()
    sessions = [services.issue_auth_tokens(user=user) for _ in range(THREADS)]
    calls = [partial(services.rotate_refresh_token, raw_refresh_token=s.refresh_token) for s in sessions]
    oks, errs = split(run_concurrently(calls))
    assert not errs, errs
    assert len({t.refresh_token for t in oks}) == THREADS
