"""Permissions de l'API commandes client (/api/v1/orders/...)."""

from rest_framework.permissions import BasePermission

from apps.accounts.models import UserRole


class IsCustomer(BasePermission):
    """Autorise exclusivement un utilisateur authentifié au rôle CUSTOMER."""

    message = "Accès réservé aux comptes clients."

    def has_permission(self, request, view) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.role == UserRole.CUSTOMER)
