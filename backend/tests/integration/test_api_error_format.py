"""Format d'erreur unifié {code, message, details} sur TOUS les endpoints.

Chaque scénario d'échec est exécuté contre la vraie pile HTTP ; on vérifie :
format exact, Content-Type JSON, absence de fuite interne, négociation de contenu.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace

import pytest
from freezegun import freeze_time
from rest_framework.test import APIClient
from rest_framework_simplejwt.settings import api_settings as jwt_settings

from apps.accounts import services
from tests.api_helpers import bearer, set_cookie
from tests.constants import (
    URL_HEALTH,
    URL_LOGIN,
    URL_LOGOUT,
    URL_ME,
    URL_REFRESH,
    URL_REGISTER,
    VALID_PASSWORD,
)
from tests.helpers import assert_unified_error

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

LEAK_MARKERS = [
    "traceback", "site-packages", 'file "', "psycopg", "django.db", "rest_framework",
    "select ", "insert into", "accounts_user", "settings.py", "/home/", "c:\\",
]


def anon():
    return APIClient()


def expired_me(e):
    later = datetime.now(dt_timezone.utc) + jwt_settings.ACCESS_TOKEN_LIFETIME + timedelta(minutes=1)
    with freeze_time(later):
        return e.auth.get(URL_ME)


def garbage_cookie(url):
    def call(e):
        c = anon()
        set_cookie(c, "garbage")
        return c.post(url)
    return call


def register_conflict(e):
    return anon().post(
        URL_REGISTER,
        {"email": e.customer.email, "phone": "+2250900000001", "full_name": "Nom Valide", "password": VALID_PASSWORD},
        format="json",
    )


def me_garbage(e):
    c = anon()
    bearer(c, "ceci.n.est.pas.un.jwt")
    return c.get(URL_ME)


# nom -> (appel, statut attendu)
SCENARIOS = {
    "health_post": (lambda e: anon().post(URL_HEALTH), 405),
    "register_get": (lambda e: anon().get(URL_REGISTER), 405),
    "register_invalid_json": (lambda e: anon().post(URL_REGISTER, data="{", content_type="application/json"), 400),
    "register_media_type": (lambda e: anon().post(URL_REGISTER, data="a=1", content_type="text/plain"), 415),
    "register_validation": (lambda e: anon().post(URL_REGISTER, {}, format="json"), 400),
    "register_conflict": (register_conflict, 409),
    "login_wrong_password": (lambda e: anon().post(URL_LOGIN, {"email": e.customer.email, "password": "Mauvais!Mdp-1"}, format="json"), 401),
    "login_validation": (lambda e: anon().post(URL_LOGIN, {}, format="json"), 400),
    "login_get": (lambda e: anon().get(URL_LOGIN), 405),
    "refresh_no_cookie": (lambda e: anon().post(URL_REFRESH), 401),
    "refresh_garbage_cookie": (garbage_cookie(URL_REFRESH), 401),
    "refresh_get": (lambda e: anon().get(URL_REFRESH), 405),
    "logout_get": (lambda e: anon().get(URL_LOGOUT), 405),
    "me_anonymous": (lambda e: anon().get(URL_ME), 401),
    "me_garbage_token": (me_garbage, 401),
    "me_expired_token": (expired_me, 401),
    "me_post": (lambda e: e.auth.post(URL_ME), 405),
    "me_put": (lambda e: e.auth.put(URL_ME, {}, format="json"), 405),
    "me_patch_invalid": (lambda e: e.auth.patch(URL_ME, {"phone": "pas-un-numero"}, format="json"), 400),
    "me_patch_conflict": (lambda e: e.auth.patch(URL_ME, {"phone": e.other.phone}, format="json"), 409),
    "unknown_route": (lambda e: anon().get("/api/v1/cette-route-n-existe-pas/"), 404),
    "unknown_auth_route": (lambda e: anon().get("/api/v1/auth/inconnue/"), 404),
}
VALIDATION_SCENARIOS = ["register_validation", "login_validation", "me_patch_invalid"]
UNAUTHENTICATED_SCENARIOS = ["me_anonymous", "me_garbage_token", "me_expired_token"]


@pytest.fixture
def env(db, customer, other_customer, auth_client):
    return SimpleNamespace(customer=customer, other=other_customer, auth=auth_client(customer))


@pytest.fixture(autouse=True)
def _no_debug(settings):
    settings.DEBUG = False


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_error_uses_the_unified_format(env, name):
    call, status = SCENARIOS[name]
    assert_unified_error(call(env), status)


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_error_body_has_no_internal_leak(env, name):
    call, _ = SCENARIOS[name]
    text = call(env).content.decode().lower()
    for marker in LEAK_MARKERS:
        assert marker not in text, f"{name}: fuite {marker!r}"


@pytest.mark.parametrize("name", VALIDATION_SCENARIOS)
def test_validation_errors_always_explain_which_field(env, name):
    call, _ = SCENARIOS[name]
    assert call(env).json()["details"], "details vide pour une erreur de validation"


@pytest.mark.parametrize("name", UNAUTHENTICATED_SCENARIOS)
def test_401_advertises_www_authenticate(env, name):
    call, _ = SCENARIOS[name]
    assert call(env).has_header("WWW-Authenticate")


@pytest.mark.parametrize("name", ["me_post", "register_get", "login_get", "refresh_get", "logout_get"])
def test_405_advertises_allow_header(env, name):
    call, _ = SCENARIOS[name]
    assert call(env).has_header("Allow")


# --------------------------------------------------------------------------
# Négociation de contenu
# --------------------------------------------------------------------------
def test_html_accept_header_still_gets_json_errors(db):
    """Sinon l'API navigable (HTML) est exposée en production."""
    browser = anon().get(URL_ME, HTTP_ACCEPT="text/html,application/xhtml+xml,*/*;q=0.8")
    assert_unified_error(browser, 401)
    strict_html = anon().get(URL_ME, HTTP_ACCEPT="text/html,application/xhtml+xml")
    assert_unified_error(strict_html, 406)


def test_unacceptable_accept_header_is_a_unified_406(db):
    r = anon().get(URL_HEALTH, HTTP_ACCEPT="application/xml")
    assert_unified_error(r, 406)


def test_wildcard_accept_header_gets_json(db):
    r = anon().get(URL_ME, HTTP_ACCEPT="*/*")
    assert_unified_error(r, 401)


# --------------------------------------------------------------------------
# URLs pathologiques : jamais de 500
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/me",              # sans slash final
        "/api/v1/%00/",
        "/api/v1/auth/login/%00",
        "/api/v1/" + "a" * 5000 + "/",
        "/api/v1/auth/../../admin",
        "//api/v1/auth/me/",
    ],
    ids=["sans_slash", "nul", "nul_suffixe", "tres_long", "traversal", "double_slash"],
)
def test_pathological_urls_never_cause_a_server_error(db, path):
    client = APIClient()
    client.raise_request_exception = False
    assert client.get(path).status_code < 500


def test_missing_trailing_slash_on_post_is_not_silently_swallowed(db):
    """POST sans slash : redirection (le body serait perdu) ou 404, jamais un succès trompeur."""
    client = APIClient()
    client.raise_request_exception = False
    r = client.post("/api/v1/auth/login", {"email": "a@b.co", "password": "x"}, format="json")
    assert r.status_code in (301, 307, 308, 404, 405)


# --------------------------------------------------------------------------
# Les succès ne ressemblent jamais à une erreur
# --------------------------------------------------------------------------
def test_successful_responses_are_not_in_error_format(env):
    me = env.auth.get(URL_ME).json()
    assert not ({"code", "message", "details"} <= set(me))
    health = anon().get(URL_HEALTH)
    assert health.status_code == 200
    assert not ({"code", "message", "details"} <= set(health.json()))
