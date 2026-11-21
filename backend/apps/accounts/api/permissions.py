"""Permissions DRF par rôle métier (CDC §3)."""

from rest_framework.permissions import BasePermission

from apps.accounts.models import UserRole


class IsCustomer(BasePermission):
    message = "Action réservée aux clients."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == UserRole.CUSTOMER
        )


class IsDepotManager(BasePermission):
    message = "Action réservée aux responsables de dépôt."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == UserRole.DEPOT_MANAGER
        )


class IsPlatformAdmin(BasePermission):
    message = "Action réservée aux administrateurs de la plateforme."

    def has_permission(self, request, view) -> bool:
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == UserRole.ADMIN
        )
