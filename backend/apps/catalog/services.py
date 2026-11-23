"""Services métier du catalogue central (validation/refus des propositions produits)."""

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import (
    Brand,
    Product,
    ProductProposal,
    ProductProposalStatus,
    ProductStatus,
)
from apps.core.exceptions import ConflictDomainError, ValidationDomainError
from apps.core.services import record_audit_log


@transaction.atomic
def approve_product_proposal(
    *,
    proposal: ProductProposal,
    actor: User,
    review_note: str = "",
) -> Product:
    """Valide une proposition de produit, publie le produit central et journalise l'action."""
    locked = (
        ProductProposal.objects.select_for_update()
        .select_related("depot")
        .get(pk=proposal.pk)
    )
    if locked.status != ProductProposalStatus.PENDING:
        raise ConflictDomainError(
            "Cette proposition de produit a déjà été traitée.",
            code="PROPOSAL_ALREADY_REVIEWED",
        )

    brand_name = locked.proposed_brand_name.strip()
    brand = Brand.objects.filter(name__iexact=brand_name).first()
    if brand is None:
        try:
            with transaction.atomic():
                brand = Brand.objects.create(name=brand_name, is_active=True)
        except IntegrityError:
            brand = Brand.objects.get(name__iexact=brand_name)
    if not brand.is_active:
        brand.is_active = True
        brand.save(update_fields=["is_active", "updated_at"])

    default_name = locked.name.strip() or f"{brand.name} {locked.capacity_kg:g} kg"
    product, created = Product.objects.get_or_create(
        brand=brand,
        capacity_kg=locked.capacity_kg,
        product_type=locked.product_type,
        defaults={
            "name": default_name,
            "description": locked.description,
            "status": ProductStatus.PUBLISHED,
        },
    )
    if not created and product.status != ProductStatus.PUBLISHED:
        product.status = ProductStatus.PUBLISHED
        product.save(update_fields=["status", "updated_at"])

    before = {"status": locked.status}
    locked.status = ProductProposalStatus.APPROVED
    locked.reviewed_by = actor
    locked.reviewed_at = timezone.now()
    locked.review_note = review_note.strip()
    locked.created_product = product
    locked.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "created_product",
            "updated_at",
        ]
    )

    record_audit_log(
        actor=actor,
        action="PRODUCT_PROPOSAL_APPROVED",
        resource_type="ProductProposal",
        resource_id=locked.pk,
        before_state=before,
        after_state={
            "status": locked.status,
            "created_product_id": str(product.pk),
        },
        reason=locked.review_note,
    )
    return product


@transaction.atomic
def reject_product_proposal(
    *,
    proposal: ProductProposal,
    actor: User,
    review_note: str,
) -> ProductProposal:
    """Refuse une proposition de produit avec motif obligatoire et journalise l'action."""
    locked = ProductProposal.objects.select_for_update().get(pk=proposal.pk)
    if locked.status != ProductProposalStatus.PENDING:
        raise ConflictDomainError(
            "Cette proposition de produit a déjà été traitée.",
            code="PROPOSAL_ALREADY_REVIEWED",
        )
    if not review_note or not review_note.strip():
        raise ValidationDomainError(
            "Un motif est obligatoire pour refuser une proposition de produit.",
            details={"review_note": ["Ce champ est obligatoire."]},
        )

    before = {"status": locked.status}
    locked.status = ProductProposalStatus.REJECTED
    locked.reviewed_by = actor
    locked.reviewed_at = timezone.now()
    locked.review_note = review_note.strip()
    locked.save(
        update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"]
    )

    record_audit_log(
        actor=actor,
        action="PRODUCT_PROPOSAL_REJECTED",
        resource_type="ProductProposal",
        resource_id=locked.pk,
        before_state=before,
        after_state={"status": locked.status},
        reason=locked.review_note,
    )
    return locked
