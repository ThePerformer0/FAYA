"""Sécurité transverse du Jalon 0.

Plusieurs tests sont des CONTRÔLES DE DURCISSEMENT : un échec est un finding à
analyser, pas forcément une régression. Lancer avec `-rs` pour voir aussi les
tests ignorés (« FINDING : ... » = fonctionnalité de sécurité absente).
"""
import importlib
import json
import logging
import statistics
import time
import uuid
from datetime import timedelta

import jwt
import pytest
from django.conf import settings as django_settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.settings import api_settings as jwt_settings

from apps.accounts import services
from apps.accounts.models import User
from tests.api_helpers import (
    bearer,
    cookie_name,
    cookie_value,
    decode_unverified,
    set_cookie,
)
from tests.constants import (
    CODE_RATE_LIMITED,
    URL_HEALTH,
    URL_LOGIN,
    URL_LOGOUT,
    URL_ME,
    URL_REFRESH,
    URL_REGISTER,
    VALID_PASSWORD,
)
from tests.helpers import assert_unified_error, create_user

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_n = iter(range(90000, 99999))


def load_settings_module(*names):
    for name in names:
        try:
            return importlib.import_module(name)
        except Exception:  # module absent, ou variables d'environnement manquantes
            continue
    pytest.skip(f"Aucun module de settings importable parmi {names}")


def register_payload(**overrides):
    n = next(_n)
    data = {"email": f"sec{n}@example.com", "phone": f"+22504{n:08d}",
            "full_name": "Test Sécurité", "password": VALID_PASSWORD}
    data.update(overrides)
    return data


def tolerant_client():
    client = APIClient()
    client.raise_request_exception = False
    return client


# ==========================================================================
# Configuration
# ==========================================================================
class TestConfiguration:
    def test_argon2_is_the_first_hasher_in_base_settings(self):
        base = load_settings_module("config.settings.base")
        hashers = getattr(base, "PASSWORD_HASHERS", None)
        if not hashers:
            pytest.skip("PASSWORD_HASHERS non défini dans base")
        assert "Argon2" in hashers[0]

    def test_password_validators_are_all_configured(self):
        validators = " ".join(v["NAME"] for v in django_settings.AUTH_PASSWORD_VALIDATORS)
        for name in ("UserAttributeSimilarityValidator", "MinimumLengthValidator",
                     "CommonPasswordValidator", "NumericPasswordValidator"):
            assert name in validators

    def test_minimum_password_length_is_at_least_8(self):
        for v in django_settings.AUTH_PASSWORD_VALIDATORS:
            if v["NAME"].endswith("MinimumLengthValidator"):
                assert v.get("OPTIONS", {}).get("min_length", 8) >= 8

    def test_blacklist_app_is_installed(self):
        assert "rest_framework_simplejwt.token_blacklist" in django_settings.INSTALLED_APPS

    def test_refresh_rotation_and_blacklist_are_enabled(self):
        assert jwt_settings.ROTATE_REFRESH_TOKENS is True
        assert jwt_settings.BLACKLIST_AFTER_ROTATION is True

    def test_token_lifetimes_are_sane(self):
        assert timedelta(minutes=1) <= jwt_settings.ACCESS_TOKEN_LIFETIME <= timedelta(minutes=30)
        assert jwt_settings.ACCESS_TOKEN_LIFETIME < jwt_settings.REFRESH_TOKEN_LIFETIME <= timedelta(days=30)

    def test_jwt_algorithm_is_not_none_and_is_a_known_secure_one(self):
        assert str(jwt_settings.ALGORITHM).upper() in {
            "HS256", "HS384", "HS512", "RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "EDDSA"}

    def test_session_authentication_is_not_a_default_authenticator(self):
        """SessionAuthentication ouvrirait une surface CSRF sur toute l'API."""
        classes = django_settings.REST_FRAMEWORK.get("DEFAULT_AUTHENTICATION_CLASSES", [])
        assert not any("SessionAuthentication" in str(c) for c in classes)

    def test_default_permission_is_authenticated_secure_by_default(self):
        perms = django_settings.REST_FRAMEWORK.get("DEFAULT_PERMISSION_CLASSES", [])
        assert any("IsAuthenticated" in str(p) for p in perms), (
            "permission par défaut = AllowAny : toute nouvelle vue sans permission explicite est publique")

    def test_custom_exception_handler_is_configured(self):
        assert django_settings.REST_FRAMEWORK.get("EXCEPTION_HANDLER")

    def test_production_cookie_is_secure(self):
        prod = load_settings_module("config.settings.prod", "config.settings.production")
        assert getattr(prod, "AUTH_REFRESH_COOKIE_SECURE", None) is True

    def test_production_debug_is_off_and_hosts_are_restricted(self):
        prod = load_settings_module("config.settings.prod", "config.settings.production")
        assert prod.DEBUG is False
        assert "*" not in getattr(prod, "ALLOWED_HOSTS", [])

    def test_production_secret_key_is_not_the_insecure_default(self):
        prod = load_settings_module("config.settings.prod", "config.settings.production")
        key = prod.SECRET_KEY
        assert len(key) >= 32 and not key.startswith("django-insecure")


# ==========================================================================
# Hachage des mots de passe (Argon2 réel, même si les tests utilisent MD5)
# ==========================================================================
class TestPasswordHashing:
    @pytest.fixture(autouse=True)
    def _argon2(self):
        pytest.importorskip("argon2")

    def test_argon2_hash_format_and_verification(self):
        hashed = make_password(VALID_PASSWORD, hasher="argon2")
        assert hashed.startswith("argon2$")
        assert VALID_PASSWORD not in hashed
        assert check_password(VALID_PASSWORD, hashed)
        assert not check_password(VALID_PASSWORD + "x", hashed)

    def test_each_hash_uses_a_new_salt(self):
        assert make_password(VALID_PASSWORD, hasher="argon2") != make_password(VALID_PASSWORD, hasher="argon2")

    def test_hashing_a_10000_char_password_is_bounded_in_time(self):
        start = time.perf_counter()
        make_password("Aa1!" * 2500, hasher="argon2")
        assert time.perf_counter() - start < 5


# ==========================================================================
# Anti-énumération par le temps de réponse (Argon2 réel forcé)
# ==========================================================================
def test_login_timing_does_not_reveal_which_emails_exist(settings):
    pytest.importorskip("argon2")
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]
    user = create_user()
    client = APIClient()

    def timed(email):
        start = time.perf_counter()
        client.post(URL_LOGIN, {"email": email, "password": "Mauvais!Mdp-1"}, format="json")
        return time.perf_counter() - start

    timed(user.email)  # échauffement
    known = [timed(user.email) for _ in range(5)]
    unknown = [timed(f"inconnu{i}@example.com") for i in range(5)]
    median_known = statistics.median(known)
    if median_known < 0.005:
        pytest.skip("hachage Argon2 trop rapide pour mesurer une différence")
    assert statistics.median(unknown) >= 0.3 * median_known, (
        f"un email inconnu répond {median_known / max(statistics.median(unknown), 1e-9):.0f}x plus vite : "
        "le service ne hache pas le mot de passe pour les comptes inexistants")


# ==========================================================================
# Jetons correctement signés mais aux claims hostiles
# ==========================================================================
class TestSignedButHostileClaims:
    @pytest.fixture
    def base_payload(self, customer):
        return decode_unverified(services.issue_auth_tokens(user=customer).access_token)

    def call(self, payload):
        token = jwt.encode(payload, jwt_settings.SIGNING_KEY, algorithm=jwt_settings.ALGORITHM)
        client = tolerant_client()
        bearer(client, token)
        return client.get(URL_ME)

    def test_sanity_a_correctly_signed_clean_token_works(self, base_payload):
        assert self.call(base_payload).status_code == 200

    def test_missing_exp(self, base_payload):
        base_payload.pop("exp")
        assert_unified_error(self.call(base_payload), 401)

    def test_expired_exp(self, base_payload):
        base_payload["exp"] = 1
        assert_unified_error(self.call(base_payload), 401)

    def test_refresh_type_token_used_as_access(self, base_payload):
        base_payload["token_type"] = "refresh"
        assert_unified_error(self.call(base_payload), 401)

    def test_missing_jti(self, base_payload):
        base_payload.pop("jti")
        assert_unified_error(self.call(base_payload), 401)

    def test_missing_user_id(self, base_payload):
        base_payload.pop(jwt_settings.USER_ID_CLAIM)
        assert_unified_error(self.call(base_payload), 401)

    def test_unknown_user_id(self, base_payload):
        base_payload[jwt_settings.USER_ID_CLAIM] = str(uuid.uuid4())
        assert_unified_error(self.call(base_payload), 401)

    @pytest.mark.parametrize("value", ["not-a-uuid", "1", "' OR '1'='1", "", "0" * 500, 12345, None],
                             ids=["non_uuid", "entier_str", "sqli", "vide", "tres_long", "entier", "null"])
    def test_malformed_user_id_is_a_401_not_a_500(self, base_payload, value):
        base_payload[jwt_settings.USER_ID_CLAIM] = value
        assert_unified_error(self.call(base_payload), 401)

    def test_access_token_claims_contain_no_personal_data(self, customer):
        payload = decode_unverified(services.issue_auth_tokens(user=customer).access_token)
        blob = json.dumps(payload).lower()
        for secret in (customer.email.lower(), customer.phone, customer.full_name.lower()):
            assert secret not in blob


# ==========================================================================
# Jetons dans des canaux non prévus
# ==========================================================================
@pytest.mark.parametrize("param", ["access_token", "token", "jwt", "access"])
def test_access_token_in_query_string_is_not_accepted(customer, param):
    token = services.issue_auth_tokens(user=customer).access_token
    r = APIClient().get(f"{URL_ME}?{param}={token}")
    assert_unified_error(r, 401)


def test_http_method_override_header_is_not_honoured(auth_client, customer):
    client = auth_client(customer)
    r = client.get(URL_ME, HTTP_X_HTTP_METHOD_OVERRIDE="DELETE")
    assert r.status_code == 200
    assert User.objects.filter(pk=customer.pk).exists()


# ==========================================================================
# Throttling / force brute
# ==========================================================================
ATTEMPTS = 60
THROTTLE_CASES = {
    "login": lambda c, i: c.post(URL_LOGIN, {"email": f"x{i}@example.com", "password": "Mauvais!Mdp-1"}, format="json"),
    "refresh": lambda c, i: c.post(URL_REFRESH),
    "register": lambda c, i: c.post(URL_REGISTER, {}, format="json"),
}


def first_throttled(call, **headers):
    client = tolerant_client()
    for i in range(ATTEMPTS):
        response = call(client, i, **headers) if headers else call(client, i)
        if response.status_code == 429:
            return response
    return None


class TestThrottling:
    @pytest.mark.parametrize("name", list(THROTTLE_CASES))
    def test_endpoint_is_rate_limited(self, name):
        response = first_throttled(THROTTLE_CASES[name])
        if response is None:
            pytest.skip(f"FINDING : aucun throttling détecté sur {name} après {ATTEMPTS} requêtes")
        assert_unified_error(response, 429, CODE_RATE_LIMITED)
        assert response.has_header("Retry-After")

    def test_throttle_is_not_bypassed_by_spoofing_x_forwarded_for(self):
        if first_throttled(THROTTLE_CASES["login"]) is None:
            pytest.skip("FINDING : aucun throttling sur login")
        cache.clear()
        client = tolerant_client()
        statuses = [
            client.post(URL_LOGIN, {"email": f"y{i}@example.com", "password": "Mauvais!Mdp-1"},
                        format="json", HTTP_X_FORWARDED_FOR=f"203.0.113.{i % 250}").status_code
            for i in range(ATTEMPTS)
        ]
        assert 429 in statuses, (
            "throttle contournable en changeant X-Forwarded-For (configurer NUM_PROXIES / proxy de confiance)")


# ==========================================================================
# En-têtes, cache, cookies
# ==========================================================================
def _register(client, user):
    return client.post(URL_REGISTER, register_payload(), format="json")


def _login(client, user):
    return client.post(URL_LOGIN, {"email": user.email, "password": VALID_PASSWORD}, format="json")


def _refresh(client, user):
    set_cookie(client, services.issue_auth_tokens(user=user).refresh_token)
    return client.post(URL_REFRESH)


def _me(client, user):
    bearer(client, services.issue_auth_tokens(user=user).access_token)
    return client.get(URL_ME)


SENSITIVE = {"register": _register, "login": _login, "refresh": _refresh, "me": _me}


class TestHeadersAndCookies:
    @pytest.mark.parametrize("name", list(SENSITIVE))
    def test_sensitive_responses_are_not_cacheable(self, customer, name):
        r = SENSITIVE[name](APIClient(), customer)
        assert r.status_code in (200, 201)
        assert "no-store" in r.get("Cache-Control", "").lower(), (
            f"{name}: Cache-Control={r.get('Cache-Control')!r} (jetons / données personnelles)")

    @pytest.mark.parametrize("url", [URL_HEALTH, URL_ME])
    def test_nosniff_header_on_api_responses(self, url):
        assert APIClient().get(url).get("X-Content-Type-Options") == "nosniff"

    @pytest.mark.parametrize("name", ["register", "login", "refresh"])
    def test_only_the_refresh_cookie_is_ever_set(self, customer, name):
        r = SENSITIVE[name](APIClient(), customer)
        assert set(r.cookies) == {cookie_name()}, f"cookies inattendus : {list(r.cookies)}"

    @pytest.mark.parametrize("url", [URL_HEALTH, URL_ME])
    def test_read_endpoints_set_no_cookie(self, auth_client, customer, url):
        assert not auth_client(customer).get(url).cookies

    def test_logout_only_touches_the_refresh_cookie(self, customer):
        client = APIClient()
        set_cookie(client, services.issue_auth_tokens(user=customer).refresh_token)
        assert set(client.post(URL_LOGOUT).cookies) == {cookie_name()}

    def test_disallowed_host_header_is_refused(self, settings):
        if "*" in settings.ALLOWED_HOSTS:
            pytest.skip("FINDING : ALLOWED_HOSTS contient '*' dans les settings de test")
        assert tolerant_client().get(URL_HEALTH, HTTP_HOST="evil.example.com").status_code == 400


# ==========================================================================
# CORS
# ==========================================================================
EVIL = "https://evil.example"


def preflight(origin, path=URL_LOGIN):
    return APIClient().options(
        path, HTTP_ORIGIN=origin, HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type,authorization")


def assert_origin_not_trusted(response, origin):
    allow = response.get("Access-Control-Allow-Origin")
    assert allow != origin
    if allow == "*":
        assert response.get("Access-Control-Allow-Credentials", "").lower() != "true"


class TestCors:
    @pytest.mark.parametrize("origin", [EVIL, "null", "http://localhost:1", "https://faya.evil.example"])
    def test_untrusted_origin_is_never_allowed_on_preflight(self, db, origin):
        assert_origin_not_trusted(preflight(origin), origin)

    def test_untrusted_origin_is_never_allowed_on_simple_requests(self, db):
        r = APIClient().get(URL_HEALTH, HTTP_ORIGIN=EVIL)
        assert_origin_not_trusted(r, EVIL)

    def test_wildcard_origins_are_not_combined_with_credentials(self):
        assert not (getattr(django_settings, "CORS_ALLOW_ALL_ORIGINS", False)
                    and getattr(django_settings, "CORS_ALLOW_CREDENTIALS", False))

    def test_trusted_origin_gets_credentials_for_the_cookie_flow(self, db):
        allowed = list(getattr(django_settings, "CORS_ALLOWED_ORIGINS", []))
        if not allowed:
            pytest.skip("Aucune origine CORS configurée (front servi depuis la même origine)")
        r = preflight(allowed[0], URL_REFRESH)
        assert r.get("Access-Control-Allow-Origin") == allowed[0]
        assert r.get("Access-Control-Allow-Credentials", "").lower() == "true"

    def test_lookalike_of_a_trusted_origin_is_refused(self, db):
        allowed = list(getattr(django_settings, "CORS_ALLOWED_ORIGINS", []))
        if not allowed:
            pytest.skip("Aucune origine CORS configurée")
        for fake in (allowed[0] + ".evil.example", allowed[0].replace("https://", "https://evil-")):
            assert_origin_not_trusted(preflight(fake), fake)


# ==========================================================================
# Injection / contenu hostile
# ==========================================================================
HOSTILE_NAMES = [
    "<script>alert(1)</script>",
    "' OR 1=1 --",
    "${7*7} {{7*7}} {%7*7%}",
    "../../etc/passwd",
    "\u202eevil\u202c",
    "nom\r\nSet-Cookie: pwned=1",
    "Robert'); DROP TABLE accounts_user;--",
]


@pytest.mark.parametrize("name", HOSTILE_NAMES, ids=range(len(HOSTILE_NAMES)))
def test_hostile_full_name_is_stored_inertly_and_returned_as_json(name):
    client = tolerant_client()
    data = register_payload(full_name=name)
    r = client.post(URL_REGISTER, data, format="json")
    assert r.status_code in (201, 400), r.content[:200]
    assert r["Content-Type"].startswith("application/json")
    assert set(r.cookies) <= {cookie_name()}, "injection d'un cookie via full_name"
    assert "pwned" not in str(r.cookies)
    if r.status_code == 201:
        assert User.objects.get(phone=data["phone"]).full_name == name.strip()
    assert User.objects.count() == (1 if r.status_code == 201 else 0)


# ==========================================================================
# Journaux : aucun secret
# ==========================================================================
def test_secrets_never_appear_in_logs(caplog, customer):
    caplog.set_level(logging.DEBUG)
    client = APIClient()
    reg = client.post(URL_REGISTER, register_payload(), format="json")
    login = _login(client, customer)
    refresh = client.post(URL_REFRESH)
    client.post(URL_LOGIN, {"email": customer.email, "password": "Mauvais!Mdp-1"}, format="json")
    secrets = [VALID_PASSWORD, "Mauvais!Mdp-1", cookie_value(reg), cookie_value(login), cookie_value(refresh),
               reg.json()["access_token"], login.json()["access_token"]]
    for secret in filter(None, secrets):
        assert secret not in caplog.text, "secret présent dans les journaux"
