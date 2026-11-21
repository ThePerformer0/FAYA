"""Limitation de débit (throttling) sur les endpoints sensibles d'authentification."""

from rest_framework.throttling import SimpleRateThrottle


class AuthIPRateThrottle(SimpleRateThrottle):
    """Limite le nombre de tentatives par adresse IP réelle (NUM_PROXIES configuré)."""

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class LoginRateThrottle(AuthIPRateThrottle):
    scope = "auth_login"


class RegisterRateThrottle(AuthIPRateThrottle):
    scope = "auth_register"


class RefreshRateThrottle(AuthIPRateThrottle):
    scope = "auth_refresh"
