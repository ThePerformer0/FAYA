"""PostgreSQL concurrency tests for depot status transitions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import time
from threading import Barrier

import pytest
from django.db import close_old_connections

from apps.accounts.models import UserRole
from apps.core.exceptions import ConflictDomainError
from apps.core.models import AuditLog
from apps.depots.models import Depot, DepotStatus
from apps.depots.services import change_depot_status
from tests.factories_depots import make_depot
from tests.helpers import create_user

pytestmark = [pytest.mark.concurrency, pytest.mark.django_db(transaction=True)]


def _status_worker(depot_id, actor_id, new_status, barrier, index):
    try:
        from apps.accounts.models import User
        depot = Depot.objects.get(pk=depot_id)
        actor = User.objects.get(pk=actor_id)
        barrier.wait(timeout=15)
        change_depot_status(depot=depot, new_status=new_status, actor=actor, reason=f"Concurrent change {index}")
        return "success"
    except ConflictDomainError as exc:
        return ("conflict", exc.code)
    except Exception as exc:
        return ("unexpected", type(exc).__name__, str(exc))
    finally:
        close_old_connections()


def test_only_one_thread_can_validate_same_pending_depot():
    depot = make_depot(status=DepotStatus.PENDING, opening_time=time(8, 0), closing_time=time(20, 0))
    actors = [create_user(role=UserRole.ADMIN) for _ in range(5)]
    barrier = Barrier(5)
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [pool.submit(_status_worker, depot.pk, actors[i].pk, DepotStatus.ACTIVE, barrier, i) for i in range(5)]
        outcomes = [future.result(timeout=30) for future in futures]

    assert outcomes.count("success") == 1, outcomes
    assert outcomes.count(("conflict", "DEPOT_STATUS_UNCHANGED")) == 4, outcomes
    assert not [item for item in outcomes if isinstance(item, tuple) and item[0] == "unexpected"]
    depot.refresh_from_db()
    assert depot.status == DepotStatus.ACTIVE
    assert AuditLog.objects.filter(resource_type="Depot", resource_id=str(depot.pk)).count() == 1


def test_conflicting_status_transitions_leave_status_consistent_with_audit_history():
    depot = make_depot(status=DepotStatus.ACTIVE, opening_time=time(8, 0), closing_time=time(20, 0))
    actors = [create_user(role=UserRole.ADMIN), create_user(role=UserRole.ADMIN)]
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_status_worker, depot.pk, actors[0].pk, DepotStatus.SUSPENDED, barrier, 0)
        second = pool.submit(_status_worker, depot.pk, actors[1].pk, DepotStatus.DISABLED, barrier, 1)
        outcomes = [first.result(timeout=30), second.result(timeout=30)]

    assert outcomes.count("success") == 2, outcomes
    assert not [item for item in outcomes if isinstance(item, tuple) and item[0] == "unexpected"]
    depot.refresh_from_db()
    logs = list(AuditLog.objects.filter(resource_type="Depot", resource_id=str(depot.pk)).order_by("created_at", "id"))
    assert len(logs) == 2
    assert logs[0].before_state.get("status") == DepotStatus.ACTIVE
    assert logs[1].before_state.get("status") == logs[0].after_state.get("status")
    assert logs[1].after_state.get("status") == depot.status
    assert {logs[0].after_state.get("status"), logs[1].after_state.get("status")} == {
        DepotStatus.SUSPENDED,
        DepotStatus.DISABLED,
    }
