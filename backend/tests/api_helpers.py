"""Helpers pour les tests d'API d'authentification (cookie refresh, JWT forgés)."""
import base64
from http.cookies import CookieError
import json

import jwt
from django.conf import settings
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken

from tests.constants import (
    REFRESH_COOKIE_NAME_FALLBACK,
    REFRESH_COOKIE_PATH,
    URL_LOGIN,
    VALID_PASSWORD,
)


def cookie_name():
    return getattr(settings, "AUTH_REFRESH_COOKIE_NAME", REFRESH_COOKIE_NAME_FALLBACK)


def morsel(response):
    return response.cookies.get(cookie_name())


def cookie_value(response):
    m = morsel(response)
    return m.value if m is not None else None


def set_cookie(client, value):
    try:
        client.cookies[cookie_name()] = value
        client.defaults.pop("HTTP_COOKIE", None)
    except CookieError:
        # Python 3.12.16+ refuse les caractères de contrôle (ex. \x00) dans SimpleCookie :
        # on envoie l'en-tête HTTP brut pour simuler un client hostile.
        client.cookies.pop(cookie_name(), None)
        client.defaults["HTTP_COOKIE"] = f"{cookie_name()}={value}"


def decode_unverified(token):
    return jwt.decode(token, options={"verify_signature": False})


def jti_of(token):
    return decode_unverified(token)["jti"]


def is_blacklisted(token):
    return BlacklistedToken.objects.filter(token__jti=jti_of(token)).exists()


def assert_refresh_cookie(response, user=None):
    """Vérifie les attributs de sécurité du cookie refresh ; retourne sa valeur."""
    m = morsel(response)
    assert m is not None, f"cookie {cookie_name()!r} absent (cookies: {list(response.cookies)})"
    assert m.value, "cookie refresh vide"
    assert m["httponly"], "cookie refresh sans HttpOnly"
    assert str(m["samesite"]).lower() == "lax", f"SameSite={m['samesite']!r}"
    assert m["path"] == REFRESH_COOKIE_PATH, f"Path={m['path']!r}"
    assert bool(m["secure"]) == bool(getattr(settings, "AUTH_REFRESH_COOKIE_SECURE", False))
    assert m["max-age"], "Max-Age absent (cookie de session ?)"
    max_age = int(m["max-age"])
    assert 0 < max_age <= int(jwt_settings.REFRESH_TOKEN_LIFETIME.total_seconds())
    payload = decode_unverified(m.value)
    assert payload["token_type"] == "refresh"
    if user is not None:
        assert payload[jwt_settings.USER_ID_CLAIM] == str(user.pk)
    return m.value


def assert_cookie_deleted(response, like=None):
    """Le cookie est expiré ; `like` = Morsel de création pour comparer Path/Domain/SameSite."""
    m = morsel(response)
    assert m is not None, "aucun Set-Cookie de suppression"
    assert m.value == ""
    assert str(m["max-age"]) == "0" or "1970" in str(m["expires"])
    assert m["path"] == REFRESH_COOKIE_PATH
    if like is not None:
        assert m["domain"] == like["domain"], "Domain de suppression différent de la création"
        assert m["path"] == like["path"], "Path de suppression différent de la création"
        assert str(m["samesite"]).lower() == str(like["samesite"]).lower()


def login(client, user, password=VALID_PASSWORD):
    response = client.post(URL_LOGIN, {"email": user.email, "password": password}, format="json")
    assert response.status_code == 200, response.content
    return response


def bearer(client, token):
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")


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


def alg_none(token):
    return jwt.encode(decode_unverified(token), key=None, algorithm="none")


def wrong_key(token):
    return jwt.encode(decode_unverified(token), key="x" * 64, algorithm="HS256")
