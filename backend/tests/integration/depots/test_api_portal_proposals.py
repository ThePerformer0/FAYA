"""Black-box integration tests for manager product proposals (Lot 4)."""
import pytest
from apps.catalog.models import ProductType, ProductProposalStatus
from apps.depots.models import DepotStatus
from tests.factories_depots import make_depot
from tests.factories_catalog import make_proposal
from tests.helpers import assert_unified_error
pytestmark = pytest.mark.django_db
URL = "/api/v1/depot/proposals/"


def _depot(manager):
    try:
        return manager.depot
    except Exception:
        return make_depot(manager=manager)


def _payload(**extra):
    result = {"proposed_brand_name": "Proposed brand", "capacity_kg": "12.5", "product_type": ProductType.BUTANE, "name": "Proposed bottle", "description": "Proposal from API test"}
    result.update(extra)
    return result


def test_list_proposals_is_scoped_and_contract(auth_client, depot_manager):
    depot = _depot(depot_manager)
    proposal = make_proposal(depot=depot, proposed_brand_name="Listed proposal")
    response = auth_client(depot_manager).get(URL)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"count", "next", "previous", "results"}
    item = next(x for x in body["results"] if x["id"] == str(proposal.pk))
    assert set(item) == {"id", "proposed_brand_name", "capacity_kg", "product_type", "name", "description", "status", "review_note", "reviewed_at", "created_product", "created_at", "updated_at"}
    assert item["status"] == ProductProposalStatus.PENDING
    assert response.headers.get("Cache-Control", "").lower().find("no-store") >= 0


def test_create_proposal_defaults_pending_and_mass_assignment_ignored(auth_client, depot_manager, other_customer):
    depot = _depot(depot_manager)
    response = auth_client(depot_manager).post(URL, _payload(status=ProductProposalStatus.APPROVED, depot=str(make_depot(manager=other_customer).pk), review_note="Injected review"), format="json")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == ProductProposalStatus.PENDING
    assert body["reviewed_at"] is None
    assert body["created_product"] is None
    assert body["review_note"] == ""
    assert body["proposed_brand_name"] == "Proposed brand"


@pytest.mark.parametrize("payload", [{"proposed_brand_name": "   "}, {"name": "   "}, {"capacity_kg": "0"}, {"capacity_kg": "-1"}, {"capacity_kg": "not-a-number"}])
def test_invalid_proposal_payload_rejected(auth_client, depot_manager, payload):
    _depot(depot_manager)
    response = auth_client(depot_manager).post(URL, _payload(**payload), format="json")
    assert_unified_error(response, status=400)


@pytest.mark.parametrize("status", [DepotStatus.SUSPENDED, DepotStatus.DISABLED])
def test_proposal_creation_blocked_for_noneditable_depot(auth_client, depot_manager, status):
    depot = _depot(depot_manager)
    depot.status = status
    depot.save(update_fields=["status"])
    response = auth_client(depot_manager).post(URL, _payload(), format="json")
    assert_unified_error(response, status=403, code="DEPOT_NOT_EDITABLE")


def test_proposals_are_isolated_between_managers(auth_client, depot_manager, other_customer):
    depot_a = _depot(depot_manager)
    depot_b = make_depot(manager=other_customer)
    foreign = make_proposal(depot=depot_b, proposed_brand_name="Foreign proposal")
    response = auth_client(depot_manager).get(URL)
    assert response.status_code == 200
    assert all(item["id"] != str(foreign.pk) for item in response.json()["results"])
