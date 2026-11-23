import pytest
from unittest.mock import patch

from apps.accounts.models import UserRole
from apps.core.models import AuditLog
from apps.core.exceptions import ConflictDomainError, ValidationDomainError
from apps.depots.models import DepotStatus
from apps.depots.services import change_depot_status
from tests.factories_depots import make_depot, make_depot_manager
from tests.helpers import create_user

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _actor():
    return create_user(role=UserRole.ADMIN)


def _state(depot):
    return {"status": depot.status}



@pytest.mark.parametrize("target", [DepotStatus.ACTIVE, DepotStatus.SUSPENDED, DepotStatus.DISABLED])
def test_valid_status_transition_updates_depot_and_audit(target):
    initial = DepotStatus.PENDING if target == DepotStatus.ACTIVE else DepotStatus.ACTIVE
    depot = make_depot(status=initial)
    actor = _actor()
    reason = "  Review completed  " if target != DepotStatus.ACTIVE else ""
    if target != DepotStatus.ACTIVE:
        result = change_depot_status(depot=depot, new_status=target, actor=actor, reason=reason)
    else:
        result = change_depot_status(depot=depot, new_status=target, actor=actor, reason=reason)
    result.refresh_from_db()
    assert result.status == target
    audit = AuditLog.objects.latest("created_at")
    expected_action = {
        DepotStatus.ACTIVE: "DEPOT_VALIDATED",
        DepotStatus.SUSPENDED: "DEPOT_SUSPENDED",
        DepotStatus.DISABLED: "DEPOT_DISABLED",
    }[target]
    assert audit.actor == actor
    assert audit.action == expected_action
    assert audit.resource_type == "Depot"
    assert audit.resource_id == str(depot.pk)
    assert audit.reason == reason.strip()
    assert audit.before_state == {"status": initial}
    assert audit.after_state == {"status": target}


def test_transition_to_pending_is_rejected_without_side_effects():
    depot = make_depot(status=DepotStatus.ACTIVE)
    actor = _actor()
    count_before = AuditLog.objects.count()
    with pytest.raises(ValidationDomainError):
        change_depot_status(depot=depot, new_status=DepotStatus.PENDING, actor=actor)
    depot.refresh_from_db()
    assert depot.status == DepotStatus.ACTIVE
    assert AuditLog.objects.count() == count_before



@pytest.mark.parametrize("target", [DepotStatus.SUSPENDED, DepotStatus.DISABLED])
@pytest.mark.parametrize("reason", ["", "   "])
def test_reason_required_for_suspended_and_disabled(target, reason):
    depot = make_depot(status=DepotStatus.ACTIVE)
    with pytest.raises(ValidationDomainError):
        change_depot_status(depot=depot, new_status=target, actor=_actor(), reason=reason)


def test_same_status_raises_conflict_without_audit():
    depot = make_depot(status=DepotStatus.ACTIVE)
    before = AuditLog.objects.count()
    with pytest.raises(ConflictDomainError):
        change_depot_status(depot=depot, new_status=DepotStatus.ACTIVE, actor=_actor())
    assert AuditLog.objects.count() == before



def test_audit_failure_rolls_back_status_change():
    depot = make_depot(status=DepotStatus.ACTIVE)
    with patch("apps.core.models.AuditLog.objects.create", side_effect=RuntimeError("audit unavailable")):
        with pytest.raises(RuntimeError):
            change_depot_status(depot=depot, new_status=DepotStatus.SUSPENDED, actor=_actor(), reason="maintenance")
    depot.refresh_from_db()
    assert depot.status == DepotStatus.ACTIVE
