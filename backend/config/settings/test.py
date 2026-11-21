"""Paramètres dédiés à la suite de tests pytest-django."""

from .base import *  # noqa: F403

DEBUG = False
AUTH_REFRESH_COOKIE_SECURE = False

# Hasher rapide en premier pour les fixtures, Argon2 disponible pour les tests sécurité
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
    "django.contrib.auth.hashers.Argon2PasswordHasher",
]
