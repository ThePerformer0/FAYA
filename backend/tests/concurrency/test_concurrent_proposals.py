"""PostgreSQL concurrency tests for proposal review services."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections

from apps.accounts.models import UserRole
from apps.catalog.models import ProductProposal, ProductProposalStatus, Brand, Product
from apps.catalog.services import approve_product_proposal, reject_product_proposal
from apps.core.exceptions import ConflictDomainError
from apps.core.models import AuditLog
from tests.factories_catalog import make_proposal
from tests.helpers import create_user

pytestmark = [pytest.mark.concurrency, pytest.mark.django_db(transaction=True)]


def _parallel(count, worker):
    barrier = Barrier(count)
    with ThreadPoolExecutor(max_workers=count) as pool:
        futures = [pool.submit(worker, barrier, index) for index in range(count)]
        return [future.result(timeout=30) for future in futures]


def _review_worker(proposal_id, actor_id, barrier, index, action="approve"):
    try:
        from apps.accounts.models import User
        proposal = ProductProposal.objects.get(pk=proposal_id)
        actor = User.objects.get(pk=actor_id)
        barrier.wait(timeout=15)
        if action == "reject":
            reject_product_proposal(proposal=proposal, actor=actor, review_note=f"Rejected {index}")
        else:
            approve_product_proposal(proposal=proposal, actor=actor, review_note=f"Approved {index}")
        return "success"
    except ConflictDomainError as exc:
        return ("conflict", exc.code)
    except Exception as exc:  # surfaced by assertions with its concrete type/message
        return ("unexpected", type(exc).__name__, str(exc))
    finally:
        close_old_connections()


def test_only_one_thread_can_approve_same_proposal(customer, admin_user):
    proposal = make_proposal(proposed_brand_name="Concurrent propane")
    actors = [create_user(role=UserRole.ADMIN) for _ in range(5)]
    outcomes = _parallel(5, lambda barrier, i: _review_worker(proposal.pk, actors[i].pk, barrier, i))

    assert outcomes.count("success") == 1, outcomes
    assert outcomes.count(("conflict", "PROPOSAL_ALREADY_REVIEWED")) == 4, outcomes
    assert not [item for item in outcomes if isinstance(item, tuple) and item[0] == "unexpected"]
    assert AuditLog.objects.filter(resource_type="ProductProposal", resource_id=str(proposal.pk)).count() == 1


def test_approval_and_rejection_race_has_exactly_one_winner():
    proposal = make_proposal(proposed_brand_name="Concurrent decision")
    actors = [create_user(role=UserRole.ADMIN), create_user(role=UserRole.ADMIN)]
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(_review_worker, proposal.pk, actors[0].pk, barrier, 0, "approve")
        second = pool.submit(_review_worker, proposal.pk, actors[1].pk, barrier, 1, "reject")
        outcomes = [first.result(timeout=30), second.result(timeout=30)]

    assert outcomes.count("success") == 1, outcomes
    assert outcomes.count(("conflict", "PROPOSAL_ALREADY_REVIEWED")) == 1, outcomes
    assert AuditLog.objects.filter(resource_type="ProductProposal", resource_id=str(proposal.pk)).count() == 1


def test_parallel_approvals_create_one_shared_brand_and_product():
    brand_name = "Éclair Concurrent"
    proposals = [
        make_proposal(proposed_brand_name=brand_name, capacity_kg="12.50"),
        make_proposal(proposed_brand_name="éCLAIR concurrent", capacity_kg="12.50"),
    ]
    actors = [create_user(role=UserRole.ADMIN), create_user(role=UserRole.ADMIN)]
    barrier = Barrier(2)

    def worker(index):
        return _review_worker(proposals[index].pk, actors[index].pk, barrier, index)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [pool.submit(worker, i) for i in range(2)]
        outcomes = [future.result(timeout=30) for future in outcomes]

    assert outcomes == ["success", "success"], outcomes
    # Compare through the ICU-lowered database expression rather than iexact under C locale.
    from django.db.models.functions import Lower
    matching_brands = Brand.objects.annotate(_lower=Lower("name")).filter(_lower="éclair concurrent")
    assert matching_brands.count() == 1
    assert Product.objects.filter(brand=matching_brands.get(), capacity_kg="12.50").count() == 1
    assert AuditLog.objects.filter(resource_type="ProductProposal", resource_id__in=[str(p.pk) for p in proposals]).count() == 2
