"""URLconf de test : vues factices qui lèvent des erreurs + vraies routes du projet.

Utilisé via `@pytest.mark.urls("tests.support_urls")`.
Suppose que l'URLconf du projet est `config.urls`.
"""
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from django.urls import include, path
from rest_framework import exceptions as drf
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import exceptions as core_exc
from tests.helpers import build_domain_error

RAISERS = {
    "domain-base": lambda: build_domain_error(core_exc.DomainError),
    "domain-validation": lambda: build_domain_error(core_exc.ValidationDomainError),
    "domain-authentication": lambda: build_domain_error(core_exc.AuthenticationDomainError),
    "domain-forbidden": lambda: build_domain_error(core_exc.ForbiddenDomainError),
    "domain-notfound": lambda: build_domain_error(core_exc.NotFoundDomainError),
    "domain-conflict": lambda: build_domain_error(core_exc.ConflictDomainError),
    "drf-validation": lambda: drf.ValidationError({"email": ["Adresse invalide."]}),
    "drf-validation-list": lambda: drf.ValidationError(["Erreur globale."]),
    "drf-not-authenticated": drf.NotAuthenticated,
    "drf-permission-denied": drf.PermissionDenied,
    "drf-not-found": drf.NotFound,
    "drf-throttled": lambda: drf.Throttled(wait=5),
    "drf-api-exception": lambda: drf.APIException("boom"),
    "http404": lambda: Http404("introuvable"),
    "django-permission-denied": DjangoPermissionDenied,
    "unhandled": lambda: RuntimeError(
        "secret interne password=hunter2 table=accounts_user"
    ),
}


class RaiseView(APIView):
    """Authentification par défaut du projet (pour que 401 soit bien produit)."""

    permission_classes = [AllowAny]

    def get(self, request, kind):
        raise RAISERS[kind]()


class OnlyGetView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"ok": True})


class ParseView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        return Response({"received": request.data})


class ProtectedView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({"ok": True})


urlpatterns = [
    path("_t/raise/<str:kind>/", RaiseView.as_view()),
    path("_t/only-get/", OnlyGetView.as_view()),
    path("_t/parse/", ParseView.as_view()),
    path("_t/protected/", ProtectedView.as_view()),
    path("", include("config.urls")),
]
