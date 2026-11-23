"""Heures de la plateforme (Africa/Douala, UTC+1, sans heure d'été)."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from freezegun import freeze_time

DOUALA_TZ = ZoneInfo("Africa/Douala")
UTC = timezone.utc


def douala(year, month, day, hour=0, minute=0, second=0, microsecond=0):
    """Instant (datetime UTC aware) correspondant à cette heure murale à Douala."""
    local = datetime(year, month, day, hour, minute, second, microsecond, tzinfo=DOUALA_TZ)
    return local.astimezone(UTC)


def at_douala(*args, **kwargs):
    """Gèle l'horloge à une heure murale de Douala : `with at_douala(2026, 3, 4, 19, 30): ...`"""
    return freeze_time(douala(*args, **kwargs))