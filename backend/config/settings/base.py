"""Configuration de base Django pour le monolithe modulaire Faya."""

import os
from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent
REPO_ROOT = BASE_DIR.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    DJANGO_ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    DJANGO_TIME_ZONE=(str, "Africa/Douala"),
    POSTGRES_DB=(str, "faya"),
    POSTGRES_USER=(str, "faya"),
    POSTGRES_PASSWORD=(str, "faya_dev_password"),
    POSTGRES_HOST=(str, "localhost"),
    POSTGRES_PORT=(int, 5432),
    USE_POSTGIS=(bool, True),
    JWT_ACCESS_TOKEN_MINUTES=(int, 10),
    JWT_REFRESH_TOKEN_DAYS=(int, 14),
    AUTH_COOKIE_SECURE=(bool, True),
)

env_file = REPO_ROOT / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="unsafe-dev-key-change-me")
DEBUG = env("DJANGO_DEBUG")
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

USE_POSTGIS = env("USE_POSTGIS")

# Sous Windows natif, résolution automatique des DLL GDAL/GEOS fournies par PostgreSQL/PostGIS
if os.name == "nt":
    GDAL_LIBRARY_PATH = env("GDAL_LIBRARY_PATH", default="")
    GEOS_LIBRARY_PATH = env("GEOS_LIBRARY_PATH", default="")

    if not (GDAL_LIBRARY_PATH and GEOS_LIBRARY_PATH):
        for pg_dir in (
            Path(r"C:\Program Files\PostgreSQL\18\bin"),
            Path(r"C:\Program Files\PostgreSQL\16\bin"),
            Path(r"C:\Program Files\PostgreSQL\13\bin"),
            Path(r"C:\OSGeo4W\bin"),
        ):
            if not pg_dir.exists():
                continue
            gdal_candidates = sorted(pg_dir.glob("libgdal*.dll")) + sorted(pg_dir.glob("gdal*.dll"))
            geos_candidates = sorted(pg_dir.glob("libgeos_c*.dll")) + sorted(pg_dir.glob("geos_c*.dll"))
            if gdal_candidates and geos_candidates:
                os.add_dll_directory(str(pg_dir))
                GDAL_LIBRARY_PATH = GDAL_LIBRARY_PATH or str(gdal_candidates[0])
                GEOS_LIBRARY_PATH = GEOS_LIBRARY_PATH or str(geos_candidates[0])
                break
    else:
        os.add_dll_directory(str(Path(GDAL_LIBRARY_PATH).parent))

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

if USE_POSTGIS:
    DJANGO_APPS.append("django.contrib.gis")

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
]

LOCAL_APPS = [
    "apps.core",
    "apps.accounts",
    "apps.catalog",
    "apps.depots",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DB_ENGINE = (
    "django.contrib.gis.db.backends.postgis"
    if USE_POSTGIS
    else "django.db.backends.postgresql"
)

DATABASES = {
    "default": {
        "ENGINE": DB_ENGINE,
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("POSTGRES_PASSWORD"),
        "HOST": env("POSTGRES_HOST"),
        "PORT": env("POSTGRES_PORT"),
        "ATOMIC_REQUESTS": False,
    }
}

AUTH_USER_MODEL = "accounts.User"

# Hachage Argon2 en priorité (ADR-18)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = env("DJANGO_TIME_ZONE")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# === Django REST Framework ===
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.accounts.api.authentication.SafeJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardResultsSetPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.unified_exception_handler",
    "NUM_PROXIES": env.int("DRF_NUM_PROXIES", default=0),
    "DEFAULT_THROTTLE_RATES": {
        "auth_login": "20/minute",
        "auth_register": "15/minute",
        "auth_refresh": "30/minute",
    },
}

# === JWT Hybride (Access en RAM + Refresh en cookie HttpOnly) ===
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=env("JWT_ACCESS_TOKEN_MINUTES")),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=env("JWT_REFRESH_TOKEN_DAYS")),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

AUTH_REFRESH_COOKIE_NAME = "faya_refresh"
AUTH_REFRESH_COOKIE_PATH = "/api/v1/auth/"
AUTH_REFRESH_COOKIE_SAMESITE = "Lax"
AUTH_REFRESH_COOKIE_SECURE = env("AUTH_COOKIE_SECURE")
AUTH_REFRESH_COOKIE_MAX_AGE = env("JWT_REFRESH_TOKEN_DAYS") * 24 * 60 * 60

# === OpenAPI (drf-spectacular) ===
SPECTACULAR_SETTINGS = {
    "TITLE": "Faya API",
    "DESCRIPTION": "API REST de la plateforme PWA Faya (recherche et réservation de bouteilles de gaz).",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/v[0-9]",
}
