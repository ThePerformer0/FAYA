"""Exceptions métier typées et gestionnaire d'erreurs unifié DRF (ADR-16)."""

import logging
from typing import Any

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, JsonResponse
from rest_framework import status
from rest_framework.exceptions import (
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.response import Response
from rest_framework.views import exception_handler
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Exception métier de base traduite au format JSON unifié."""

    default_code = "DOMAIN_ERROR"
    default_status_code = status.HTTP_400_BAD_REQUEST

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code
        self.status_code = status_code or self.default_status_code
        self.details = details or {}


class ValidationDomainError(DomainError):
    default_code = "VALIDATION_ERROR"
    default_status_code = status.HTTP_400_BAD_REQUEST


class AuthenticationDomainError(DomainError):
    default_code = "AUTHENTICATION_FAILED"
    default_status_code = status.HTTP_401_UNAUTHORIZED


class ForbiddenDomainError(DomainError):
    default_code = "FORBIDDEN"
    default_status_code = status.HTTP_403_FORBIDDEN


class NotFoundDomainError(DomainError):
    default_code = "NOT_FOUND"
    default_status_code = status.HTTP_404_NOT_FOUND


class ConflictDomainError(DomainError):
    default_code = "CONFLICT"
    default_status_code = status.HTTP_409_CONFLICT


def _is_expired_token_error(exc: Exception) -> bool:
    """Distingue un JWT réellement expiré d'un jeton malformé ou falsifié."""
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        messages = detail.get("messages", [])
        if isinstance(messages, list):
            for item in messages:
                if isinstance(item, dict):
                    msg = str(item.get("message", "")).lower()
                    if "expired" in msg and "invalid" not in msg:
                        return True
        return False
    text = str(exc).lower()
    return "expired" in text and "invalid" not in text


def _set_unified_payload(
    response: Response,
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    status_code: int | None = None,
) -> Response:
    """Met à jour la réponse DRF en place afin de préserver ses en-têtes HTTP."""
    if status_code is not None:
        response.status_code = status_code
    response.data = {
        "code": code,
        "message": message,
        "details": details if details is not None else {},
    }
    if response.status_code == status.HTTP_401_UNAUTHORIZED and not response.has_header(
        "WWW-Authenticate"
    ):
        response["WWW-Authenticate"] = 'Bearer realm="api"'
    return response


def unified_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Garantit systématiquement le format { code, message, details }."""

    if isinstance(exc, DomainError):
        response = Response(
            {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
            status=exc.status_code,
        )
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            response["WWW-Authenticate"] = 'Bearer realm="api"'
        return response

    response = exception_handler(exc, context)
    if response is None:
        logger.exception("Erreur interne non gérée dans l'API", exc_info=exc)
        return Response(
            {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "Une erreur interne est survenue.",
                "details": {},
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if isinstance(exc, ValidationError):
        details = (
            response.data
            if isinstance(response.data, dict)
            else {"non_field_errors": response.data}
        )
        return _set_unified_payload(
            response,
            code="VALIDATION_ERROR",
            message="Les données soumises sont invalides.",
            details=details,
        )

    if isinstance(exc, (InvalidToken, TokenError)):
        if _is_expired_token_error(exc):
            return _set_unified_payload(
                response,
                code="TOKEN_EXPIRED",
                message="Le jeton d'authentification est expiré.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        return _set_unified_payload(
            response,
            code="AUTHENTICATION_FAILED",
            message="Le jeton d'authentification est invalide.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, NotAuthenticated):
        return _set_unified_payload(
            response,
            code="UNAUTHENTICATED",
            message="Authentification requise.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, AuthenticationFailed):
        return _set_unified_payload(
            response,
            code="AUTHENTICATION_FAILED",
            message=str(exc.detail),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, (PermissionDenied, DjangoPermissionDenied)):
        message = (
            str(exc.detail)
            if isinstance(exc, PermissionDenied)
            else (str(exc) or "Vous n'avez pas la permission d'effectuer cette action.")
        )
        return _set_unified_payload(
            response,
            code="FORBIDDEN",
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, (NotFound, Http404)):
        return _set_unified_payload(
            response,
            code="NOT_FOUND",
            message="Ressource introuvable.",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, Throttled):
        return _set_unified_payload(
            response,
            code="RATE_LIMITED",
            message="Trop de requêtes. Veuillez réessayer ultérieurement.",
            details={"wait_seconds": exc.wait},
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    detail = response.data.get("detail") if isinstance(response.data, dict) else None
    return _set_unified_payload(
        response,
        code="API_ERROR",
        message=str(detail) if detail else "Une erreur est survenue.",
        details=response.data if isinstance(response.data, dict) else {},
    )


def json_handler404(request, exception=None) -> JsonResponse:
    """Garantit le format d'erreur JSON unifié pour les routes API inconnues."""
    return JsonResponse(
        {
            "code": "NOT_FOUND",
            "message": "Ressource introuvable.",
            "details": {},
        },
        status=status.HTTP_404_NOT_FOUND,
    )


def json_handler500(request) -> JsonResponse:
    """Garantit une réponse 500 JSON générique sans fuite d'information."""
    return JsonResponse(
        {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "Une erreur interne est survenue.",
            "details": {},
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
