"""Authentification JWT durcie contre les claims user_id malformés."""

import uuid

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework_simplejwt.settings import api_settings


class SafeJWTAuthentication(JWTAuthentication):
    """Valide le format UUID du user_id avant d'interroger la base de données."""

    def get_user(self, validated_token):
        user_id = validated_token.get(api_settings.USER_ID_CLAIM)
        if user_id is None:
            raise AuthenticationFailed("Le jeton ne contient aucun identifiant utilisateur.")
        try:
            uuid.UUID(str(user_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise AuthenticationFailed("Identifiant utilisateur invalide dans le jeton.") from exc

        try:
            return super().get_user(validated_token)
        except (DjangoValidationError, ValueError, TypeError) as exc:
            raise AuthenticationFailed("Identifiant utilisateur invalide dans le jeton.") from exc


class SafeJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.api.authentication.SafeJWTAuthentication"
    name = "jwtAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
