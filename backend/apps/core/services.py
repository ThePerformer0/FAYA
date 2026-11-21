"""Services transversaux du module core (audit)."""

from typing import Any

from apps.core.models import AuditLog


def record_audit_log(
    *,
    actor: Any,
    action: str,
    resource_type: str,
    resource_id: Any,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    reason: str = "",
) -> AuditLog:
    """Enregistre un événement immuable dans le journal d'audit."""
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id),
        before_state=before_state,
        after_state=after_state,
        reason=reason,
    )
