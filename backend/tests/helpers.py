"""Helpers partagés (aucune dépendance supplémentaire type factory_boy)."""
from __future__ import annotations

import inspect
import itertools

from tests.constants import ERROR_KEYS, VALID_PASSWORD

_counter = itertools.count(1)


def create_user(
    *,
    role=None,
    email=None,
    phone=None,
    full_name=None,
    password=VALID_PASSWORD,
    **extra,
):
    """Crée un utilisateur avec des valeurs uniques (email / phone E.164)."""
    from apps.accounts.models import User, UserRole

    n = next(_counter)
    return User.objects.create_user(
        email=email or f"user{n}@example.com",
        phone=phone or f"+22507{n:08d}",
        full_name=full_name or f"Utilisateur {n}",
        password=password,
        role=role or UserRole.CUSTOMER,
        **extra,
    )


def build_domain_error(
    cls,
    message="Message de test",
    code="test_code",
    details=None,
):
    """Instancie une DomainError sans présumer de la signature exacte de __init__.

    Ne passe que les paramètres que le constructeur accepte réellement.
    """
    details = {"champ": "valeur"} if details is None else details
    params = inspect.signature(cls.__init__).parameters
    kwargs = {
        name: value
        for name, value in (("message", message), ("code", code), ("details", details))
        if name in params
    }
    return cls(**kwargs)


def assert_unified_error(response, status=None, code=None):
    """Vérifie le format d'erreur unifié {code, message, details}."""
    if status is not None:
        assert response.status_code == status, (
            f"statut {response.status_code} != {status} "
            f"(corps: {response.content[:300]!r})"
        )
    content_type = response.get("Content-Type", "")
    assert content_type.startswith("application/json"), (
        f"Content-Type inattendu {content_type!r} (corps: {response.content[:300]!r})"
    )
    body = response.json()
    assert isinstance(body, dict), f"corps non-objet: {body!r}"
    assert set(body.keys()) == ERROR_KEYS, f"clés inattendues: {sorted(body.keys())}"
    assert isinstance(body["code"], str) and body["code"], "code vide ou non-str"
    assert isinstance(body["message"], str) and body["message"], "message vide ou non-str"
    assert isinstance(body["details"], dict), "details doit être un objet"
    if code is not None:
        assert body["code"] == code
    return body
