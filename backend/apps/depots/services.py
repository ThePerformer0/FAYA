"""Services métier d'administration et de cycle de vie des dépôts."""

from django.db import transaction

from apps.accounts.models import User
from apps.core.exceptions import ConflictDomainError, ValidationDomainError
from apps.core.services import record_audit_log
from apps.depots.models import Depot, DepotStatus

_STATUS_ACTIONS = {
    DepotStatus.ACTIVE: "DEPOT_VALIDATED",
    DepotStatus.SUSPENDED: "DEPOT_SUSPENDED",
    DepotStatus.DISABLED: "DEPOT_DISABLED",
}


@transaction.atomic
def change_depot_status(
    *,
    depot: Depot,
    new_status: str,
    actor: User,
    reason: str = "",
) -> Depot:
    """Valide, suspend ou désactive un dépôt avec journalisation dans AuditLog."""
    if new_status not in _STATUS_ACTIONS:
        raise ValidationDomainError(
            "Statut de dépôt cible invalide.",
            details={"status": ["Statut non autorisé."]},
        )

    locked = Depot.objects.select_for_update().get(pk=depot.pk)
    if locked.status == new_status:
        raise ConflictDomainError(
            "Le dépôt possède déjà ce statut.",
            code="DEPOT_STATUS_UNCHANGED",
        )

    if new_status in {DepotStatus.SUSPENDED, DepotStatus.DISABLED} and not reason.strip():
        raise ValidationDomainError(
            "Un motif est obligatoire pour suspendre ou désactiver un dépôt.",
            details={"reason": ["Ce champ est obligatoire."]},
        )

    before = {"status": locked.status}
    locked.status = new_status
    locked.save(update_fields=["status", "updated_at"])

    record_audit_log(
        actor=actor,
        action=_STATUS_ACTIONS[new_status],
        resource_type="Depot",
        resource_id=locked.pk,
        before_state=before,
        after_state={"status": locked.status},
        reason=reason.strip(),
    )
    return locked
