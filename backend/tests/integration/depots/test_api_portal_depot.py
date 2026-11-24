"""Black-box integration tests for the manager depot profile endpoint (Lot 4)."""
import pytest
from apps.core.models import AuditLog
from apps.depots.models import DepotStatus
from tests.factories_depots import make_depot
from tests.helpers import assert_unified_error
pytestmark = pytest.mark.django_db
URL = "/api/v1/depot/"


def _depot(manager):
    try:
        return manager.depot
    except Exception:
        return make_depot(manager=manager)


def test_profile_get_contract_and_editable_flag(auth_client, depot_manager):
    depot = _depot(depot_manager)
    response = auth_client(depot_manager).get(URL)
    assert response.status_code == 200
    expected = {"id", "name", "description", "address", "neighborhood", "phone", "latitude", "longitude", "opening_time", "closing_time", "status", "is_editable", "open_status", "can_order", "last_order_time", "reopens_at", "created_at", "updated_at"}
    assert set(response.json()) == expected
    assert response.json()["is_editable"] is True
    assert response.headers.get("Cache-Control", "").lower().find("no-store") >= 0


@pytest.mark.parametrize("status,editable", [(DepotStatus.PENDING, True), (DepotStatus.ACTIVE, True), (DepotStatus.SUSPENDED, False), (DepotStatus.DISABLED, False)])
def test_profile_editability_matches_status(auth_client, depot_manager, status, editable):
    depot = _depot(depot_manager)
    depot.status = status
    depot.save(update_fields=["status"])
    response = auth_client(depot_manager).get(URL)
    assert response.status_code == 200
    assert response.json()["is_editable"] is editable


def test_patch_updates_profile_and_creates_audit_record(auth_client, depot_manager):
    depot = _depot(depot_manager)
    before_count = AuditLog.objects.filter(action="DEPOT_PROFILE_UPDATED", resource_type="Depot", resource_id=str(depot.pk)).count()
    response = auth_client(depot_manager).patch(URL, {"name": "Faya Test Depot", "description": "Updated through API"}, format="json")
    assert response.status_code == 200
    depot.refresh_from_db()
    assert depot.name == "Faya Test Depot"
    assert depot.description == "Updated through API"
    assert AuditLog.objects.filter(action="DEPOT_PROFILE_UPDATED", resource_type="Depot", resource_id=str(depot.pk)).count() == before_count + 1
    assert response.json()["name"] == depot.name


def test_patch_same_values_does_not_create_audit(auth_client, depot_manager):
    depot = _depot(depot_manager)
    payload = {"name": depot.name, "description": depot.description}
    before = AuditLog.objects.filter(action="DEPOT_PROFILE_UPDATED", resource_type="Depot", resource_id=str(depot.pk)).count()
    response = auth_client(depot_manager).patch(URL, payload, format="json")
    assert response.status_code == 200
    after = AuditLog.objects.filter(action="DEPOT_PROFILE_UPDATED", resource_type="Depot", resource_id=str(depot.pk)).count()
    assert after == before


@pytest.mark.parametrize("payload", [{"latitude": 4.0}, {"longitude": 9.0}, {"latitude": 91, "longitude": 0}, {"latitude": 0, "longitude": 181}, {"opening_time": "20:00", "closing_time": "08:00"}, {"name": "   "}, {"address": "   "}, {"phone": "invalid-phone"}])
def test_profile_validation_errors(payload, auth_client, depot_manager):
    _depot(depot_manager)
    response = auth_client(depot_manager).patch(URL, payload, format="json")
    assert_unified_error(response, status=400)


def test_mass_assignment_fields_are_ignored(auth_client, depot_manager, other_customer):
    depot = _depot(depot_manager)
    original_status, original_manager = depot.status, depot.manager_id
    response = auth_client(depot_manager).patch(URL, {"status": DepotStatus.DISABLED, "manager": other_customer.pk, "id": "00000000-0000-0000-0000-000000000000", "depot_id": "00000000-0000-0000-0000-000000000000"}, format="json")
    assert response.status_code == 200
    depot.refresh_from_db()
    assert depot.status == original_status and depot.manager_id == original_manager


@pytest.mark.parametrize("status", [DepotStatus.SUSPENDED, DepotStatus.DISABLED])
def test_profile_mutation_blocked_when_depot_not_editable(auth_client, depot_manager, status):
    depot = _depot(depot_manager)
    depot.status = status
    depot.save(update_fields=["status"])
    response = auth_client(depot_manager).patch(URL, {"description": "Should not apply"}, format="json")
    assert_unified_error(response, status=403, code="DEPOT_NOT_EDITABLE")
