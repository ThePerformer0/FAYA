"""Requêtes de lecture du module accounts."""

from datetime import datetime

from django.utils import timezone

from apps.accounts.models import CustomerSuspension, User


def get_active_suspension(
    *,
    user: User,
    at: datetime | None = None,
) -> CustomerSuspension | None:
    """Retourne la suspension active du client à l'instant donné, ou None."""
    now = at or timezone.now()
    return (
        CustomerSuspension.objects.filter(
            customer=user,
            lifted_at__isnull=True,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        .order_by("-ends_at")
        .first()
    )


def is_customer_suspended(*, user: User, at: datetime | None = None) -> bool:
    """Indique si le client est actuellement suspendu de commande."""
    return get_active_suspension(user=user, at=at) is not None
