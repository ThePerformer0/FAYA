"""Fabriques de données pour les suspensions (sans factory_boy)."""
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
T0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)


def utc(year, month, day, hour=0, minute=0, second=0, microsecond=0):
    return datetime(year, month, day, hour, minute, second, microsecond, tzinfo=UTC)


def make_suspension(customer, *, starts_at=None, ends_at=None, reason=None, **extra):
    """Crée une CustomerSuspension (fenêtre de 7 jours à partir de T0 par défaut)."""
    from apps.accounts.models import CustomerSuspension, SuspensionReason

    starts_at = starts_at or T0
    ends_at = ends_at or starts_at + timedelta(days=7)
    field = CustomerSuspension._meta.get_field("triggering_no_show_count")
    if not field.null and not field.has_default():
        extra.setdefault("triggering_no_show_count", 3)
    return CustomerSuspension.objects.create(
        customer=customer,
        starts_at=starts_at,
        ends_at=ends_at,
        reason=reason or SuspensionReason.MANUAL,
        **extra,
    )
