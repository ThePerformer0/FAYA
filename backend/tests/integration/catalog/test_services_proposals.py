"""Black-box integration tests for catalog proposal review services (Jalon 1, Lot 3)."""
from decimal import Decimal

import pytest
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import (
    Brand,
    Product,
    ProductProposal,
    ProductProposalStatus,
    ProductStatus,
)
from apps.catalog.services import approve_product_proposal, reject_product_proposal
from apps.core.models import AuditLog
from apps.core.exceptions import ConflictDomainError, ValidationDomainError
from apps.accounts.models import UserRole
from tests.factories_catalog import make_brand, make_product, make_proposal
from tests.helpers import create_user
from tests.constants_j1 import (
    AUDIT_PROPOSAL_APPROVED,
    AUDIT_PROPOSAL_REJECTED,
    CODE_PROPOSAL_ALREADY_REVIEWED,
)


pytestmark = pytest.mark.integration


def _actor():
    return create_user(role=UserRole.ADMIN)


def _audit_for(proposal, action):
    return AuditLog.objects.filter(
        action=action,
        resource_type="ProductProposal",
        resource_id=str(proposal.pk),
    )



@pytest.mark.django_db
def test_approve_pending_proposal_creates_brand_product_and_audit():
    actor = _actor()
    proposal = make_proposal(proposed_brand_name="  Nouvelle marque  ", name="Produit proposé")

    product = approve_product_proposal(proposal=proposal, actor=actor, review_note="  validé  ")

    proposal.refresh_from_db()
    assert isinstance(product, Product)
    assert product.status == ProductStatus.PUBLISHED
    assert product.brand.name == "Nouvelle marque"
    assert product.brand.is_active is True
    assert proposal.status == ProductProposalStatus.APPROVED
    assert proposal.reviewed_by == actor
    assert proposal.reviewed_at is not None and timezone.is_aware(proposal.reviewed_at)
    assert proposal.review_note == "validé"
    assert proposal.created_product_id == product.pk

    logs = _audit_for(proposal, AUDIT_PROPOSAL_APPROVED)
    assert logs.count() == 1
    log = logs.get()
    assert log.actor == actor
    assert log.reason == "validé"
    assert log.before_state is not None
    assert log.after_state is not None


@pytest.mark.django_db
def test_approve_proposal_reuses_case_and_accent_insensitive_brand():
    existing = make_brand(name="Éclair", is_active=True)
    proposal = make_proposal(proposed_brand_name="  éclair  ")


    product = approve_product_proposal(proposal=proposal, actor=_actor())

    assert product.brand_id == existing.pk
    assert Brand.objects.count() == 1



@pytest.mark.django_db
def test_approve_proposal_reactivates_inactive_brand():
    brand = make_brand(name="Gaz Plus", is_active=False)
    proposal = make_proposal(proposed_brand_name=" gaz plus ")


    product = approve_product_proposal(proposal=proposal, actor=_actor())

    brand.refresh_from_db()
    assert product.brand_id == brand.pk
    assert brand.is_active is True



@pytest.mark.django_db
def test_approve_proposal_reuses_existing_product_even_if_draft():
    brand = make_brand(name="Reuse Brand")
    existing = make_product(brand=brand, capacity_kg=Decimal("12.5"), status=ProductStatus.DRAFT)
    proposal = make_proposal(
        proposed_brand_name=brand.name,
        capacity_kg=Decimal("12.5"),
        product_type=existing.product_type,
    )


    result = approve_product_proposal(proposal=proposal, actor=_actor())


    existing.refresh_from_db()
    assert result.pk == existing.pk
    assert result.status == ProductStatus.PUBLISHED
    assert Product.objects.filter(brand=brand, capacity_kg=Decimal("12.5"), product_type=existing.product_type).count() == 1



@pytest.mark.django_db
def test_approve_proposal_reuses_archived_product_and_publishes_it():
    brand = make_brand(name="Archived Brand")
    existing = make_product(brand=brand, status=ProductStatus.ARCHIVED)
    proposal = make_proposal(proposed_brand_name=brand.name, capacity_kg=existing.capacity_kg, product_type=existing.product_type)

    result = approve_product_proposal(proposal=proposal, actor=_actor())

    existing.refresh_from_db()
    assert result.pk == existing.pk
    assert existing.status == ProductStatus.PUBLISHED



@pytest.mark.django_db
def test_approval_does_not_create_duplicate_for_published_product():
    brand = make_brand(name="Published Brand")
    existing = make_product(brand=brand, status=ProductStatus.PUBLISHED)
    proposal = make_proposal(proposed_brand_name=brand.name, capacity_kg=existing.capacity_kg, product_type=existing.product_type)

    result = approve_product_proposal(proposal=proposal, actor=_actor())

    assert result.pk == existing.pk
    assert Product.objects.filter(brand=brand, capacity_kg=existing.capacity_kg, product_type=existing.product_type).count() == 1



@pytest.mark.django_db
def test_approval_trims_review_note_and_empty_note_is_allowed():
    proposal = make_proposal(proposed_brand_name="Whitespace Brand")
    result = approve_product_proposal(proposal=proposal, actor=_actor(), review_note=" \n ")
    proposal.refresh_from_db()
    assert proposal.review_note == ""
    assert _audit_for(proposal, AUDIT_PROPOSAL_APPROVED).get().reason == ""
    assert result is not None



@pytest.mark.django_db
def test_approve_already_reviewed_proposal_has_no_side_effects():
    proposal = make_proposal(proposed_brand_name="Already Reviewed", status=ProductProposalStatus.REJECTED)
    brands_before = Brand.objects.count()
    products_before = Product.objects.count()
    audits_before = AuditLog.objects.count()

    with pytest.raises(ConflictDomainError) as exc:
        approve_product_proposal(proposal=proposal, actor=_actor())

    assert exc.value.code == CODE_PROPOSAL_ALREADY_REVIEWED
    assert Brand.objects.count() == brands_before
    assert Product.objects.count() == products_before
    assert AuditLog.objects.count() == audits_before



@pytest.mark.django_db
def test_reject_pending_proposal_trims_note_and_creates_audit_only():
    actor = _actor()
    proposal = make_proposal(proposed_brand_name="Must Not Create")
    brands_before = Brand.objects.count()
    products_before = Product.objects.count()


    result = reject_product_proposal(proposal=proposal, actor=actor, review_note="  hors catalogue  ")

    proposal.refresh_from_db()
    assert result.pk == proposal.pk
    assert proposal.status == ProductProposalStatus.REJECTED
    assert proposal.reviewed_by == actor
    assert proposal.reviewed_at is not None and timezone.is_aware(proposal.reviewed_at)
    assert proposal.review_note == "hors catalogue"
    assert proposal.created_product is None
    assert Brand.objects.count() == brands_before
    assert Product.objects.count() == products_before
    log = _audit_for(proposal, AUDIT_PROPOSAL_REJECTED).get()
    assert log.actor == actor
    assert log.reason == "hors catalogue"



@pytest.mark.parametrize("note", ["", "   ", "\n\t  "])
@pytest.mark.django_db
def test_reject_requires_nonblank_note(note):
    proposal = make_proposal(proposed_brand_name="Rejected Note Validation")
    before = AuditLog.objects.count()

    with pytest.raises(ValidationDomainError):
        reject_product_proposal(proposal=proposal, actor=_actor(), review_note=note)

    proposal.refresh_from_db()
    assert proposal.status == ProductProposalStatus.PENDING
    assert proposal.reviewed_by is None
    assert proposal.reviewed_at is None
    assert proposal.review_note == ""
    assert proposal.created_product is None
    assert AuditLog.objects.count() == before



@pytest.mark.parametrize("status", [ProductProposalStatus.APPROVED, ProductProposalStatus.REJECTED])
@pytest.mark.django_db
def test_reject_already_reviewed_proposal_has_no_side_effects(status):
    proposal = make_proposal(proposed_brand_name="Reviewed Reject", status=status)
    brands_before = Brand.objects.count()
    products_before = Product.objects.count()
    audits_before = AuditLog.objects.count()

    with pytest.raises(ConflictDomainError) as exc:
        reject_product_proposal(proposal=proposal, actor=_actor(), review_note="motif")

    assert exc.value.code == CODE_PROPOSAL_ALREADY_REVIEWED
    assert Brand.objects.count() == brands_before
    assert Product.objects.count() == products_before
    assert AuditLog.objects.count() == audits_before



@pytest.mark.django_db
def test_approval_and_rejection_are_atomic_on_audit_failure(monkeypatch):
    proposal = make_proposal(proposed_brand_name="Atomic Brand")
    before_brands = Brand.objects.count()
    before_products = Product.objects.count()


    def fail_create(*args, **kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(AuditLog.objects, "create", fail_create)
    with pytest.raises(RuntimeError):
        approve_product_proposal(proposal=proposal, actor=_actor())

    proposal.refresh_from_db()
    assert proposal.status == ProductProposalStatus.PENDING
    assert Brand.objects.count() == before_brands
    assert Product.objects.count() == before_products



@pytest.mark.django_db
def test_reject_service_rolls_back_when_audit_creation_fails(monkeypatch):
    proposal = make_proposal(proposed_brand_name="Atomic Reject")


    def fail_create(*args, **kwargs):
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(AuditLog.objects, "create", fail_create)
    with pytest.raises(RuntimeError):
        reject_product_proposal(proposal=proposal, actor=_actor(), review_note="motif")

    proposal.refresh_from_db()
    assert proposal.status == ProductProposalStatus.PENDING
    assert proposal.reviewed_by is None
    assert proposal.reviewed_at is None
