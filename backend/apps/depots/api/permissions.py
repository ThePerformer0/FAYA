"""Permissions d'isolation stricte pour le portail Responsable de dépôt (ADR-02, ADR-11)."""

from rest_framework.permissions import BasePermission

from apps.accounts.models import UserRole
from apps.core.exceptions import ForbiddenDomainError
from apps.depots.models import Depot


class IsDepotManagerWithDepot(BasePermission):
    """Autorise uniquement un responsable de dépôt relié à un dépôt existant."""

    message = "Accès réservé aux responsables de dépôt disposant d'un dépôt rattaché."

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.role != UserRole.DEPOT_MANAGER:
            return False
        depot = Depot.objects.filter(manager_id=user.pk).first()
        if depot is None:
            return False
        request.managed_depot = depot
        return True


def get_request_managed_depot(request) -> Depot:
    """Retourne le dépôt rattaché au responsable authentifié sans jamais lire d'ID externe."""
    depot = getattr(request, "managed_depot", None)
    if depot is None:
        depot = Depot.objects.filter(manager_id=request.user.pk).first()
    if depot is None:
        raise ForbiddenDomainError(
            "Aucun dépôt n'est rattaché à votre compte.",
            code="DEPOT_NOT_ASSIGNED",
        )
    return depot
