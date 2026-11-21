"""Permissions DRF : IsCustomer, IsDepotManager, IsPlatformAdmin.

Matrice rôle x permission, plus cas dégénérés (anonyme, rôle inconnu/None,
superuser sans rôle ADMIN).
"""
import pytest
from django.contrib.auth.models import AnonymousUser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.accounts.api.permissions import IsCustomer, IsDepotManager, IsPlatformAdmin
from apps.accounts.models import UserRole
from tests.helpers import create_user

pytestmark = [pytest.mark.unit, pytest.mark.django_db]

PERMISSIONS = {
    "IsCustomer": (IsCustomer, UserRole.CUSTOMER),
    "IsDepotManager": (IsDepotManager, UserRole.DEPOT_MANAGER),
    "IsPlatformAdmin": (IsPlatformAdmin, UserRole.ADMIN),
}
ROLES = [UserRole.CUSTOMER, UserRole.DEPOT_MANAGER, UserRole.ADMIN]


def make_request(user):
    request = Request(APIRequestFactory().get("/"))
    request.user = user
    return request


def check(permission_cls, user):
    return permission_cls().has_permission(make_request(user), object())


# --------------------------------------------------------------------------
# Matrice
# --------------------------------------------------------------------------
@pytest.mark.parametrize("perm_name", list(PERMISSIONS))
@pytest.mark.parametrize("role", ROLES)
def test_permission_matrix(perm_name, role):
    permission_cls, allowed_role = PERMISSIONS[perm_name]
    result = check(permission_cls, create_user(role=role))
    assert isinstance(result, bool)
    assert result is (role == allowed_role)


@pytest.mark.parametrize("perm_name", list(PERMISSIONS))
def test_anonymous_user_is_denied(perm_name):
    permission_cls, _ = PERMISSIONS[perm_name]
    assert check(permission_cls, AnonymousUser()) is False


@pytest.mark.parametrize("perm_name", list(PERMISSIONS))
def test_none_user_is_denied_without_crashing(perm_name):
    permission_cls, _ = PERMISSIONS[perm_name]
    assert check(permission_cls, None) is False


@pytest.mark.parametrize("perm_name", list(PERMISSIONS))
@pytest.mark.parametrize("bad_role", ["HACKER", "customer", "", None, "ADMIN "])
def test_unknown_or_malformed_role_is_denied(perm_name, bad_role):
    permission_cls, _ = PERMISSIONS[perm_name]
    user = create_user()
    user.role = bad_role
    assert check(permission_cls, user) is False


# --------------------------------------------------------------------------
# Élévation de privilèges potentielle
# --------------------------------------------------------------------------
def test_superuser_flag_alone_does_not_grant_platform_admin():
    """Choix de conception à expliciter : is_superuser/is_staff != role ADMIN."""
    user = create_user(role=UserRole.CUSTOMER, is_staff=True, is_superuser=True)
    assert check(IsPlatformAdmin, user) is False
    assert check(IsCustomer, user) is True


def test_staff_flag_alone_does_not_grant_platform_admin():
    user = create_user(role=UserRole.CUSTOMER, is_staff=True)
    assert check(IsPlatformAdmin, user) is False


def test_role_change_in_memory_is_reflected_immediately():
    user = create_user(role=UserRole.CUSTOMER)
    assert check(IsPlatformAdmin, user) is False
    user.role = UserRole.ADMIN
    assert check(IsPlatformAdmin, user) is True


# --------------------------------------------------------------------------
# Composition DRF (| et &)
# --------------------------------------------------------------------------
def test_permissions_can_be_composed_with_or():
    either = IsCustomer | IsDepotManager
    assert either().has_permission(make_request(create_user(role=UserRole.CUSTOMER)), object())
    assert either().has_permission(make_request(create_user(role=UserRole.DEPOT_MANAGER)), object())
    assert not either().has_permission(make_request(create_user(role=UserRole.ADMIN)), object())


def test_permissions_can_be_composed_with_and():
    both = IsCustomer & IsPlatformAdmin
    for role in ROLES:
        assert not both().has_permission(make_request(create_user(role=role)), object())
