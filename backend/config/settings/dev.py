"""Paramètres de développement local."""

from .base import *  # noqa: F403

DEBUG = True
AUTH_REFRESH_COOKIE_SECURE = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "api", "0.0.0.0"]
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
