"""Paramètres dédiés à la suite de tests pytest-django."""

from .base import *  # noqa: F403

DEBUG = False
AUTH_REFRESH_COOKIE_SECURE = False

# Hasher rapide uniquement pour les tests afin d'accélérer la création des fixtures
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
