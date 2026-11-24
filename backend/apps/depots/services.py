"""Services métier d'administration, de cycle de vie et du portail responsable des dépôts."""

from decimal import Decimal
from uuid import UUID

from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.catalog.models import Brand, Product, ProductProposal, ProductStatus
from apps.core.exceptions import (
    ConflictDomainError,
    NotFoundDomainError,
    ValidationDomainError,
)
from apps.core.services import record_audit_log
from apps.depots.models import (
    Depot,
    DepotProductOffer,
    DepotStatus,
    OfferExchangeBrand,
    OfferOperation,
    OperationType,
)
from apps.inventory.services import assert_depot_editable

_STATUS_ACTIONS = {
    DepotStatus.ACTIVE: "DEPOT_VALIDATED",
    DepotStatus.SUSPENDED: "DEPOT_SUSPENDED",
    DepotStatus.DISABLED: "DEPOT_DISABLED",
}


def _raise_from_django_validation_error(exc: DjangoValidationError) -> None:
    if hasattr(exc, "message_dict"):
        details = exc.message_dict
    else:
        details = {"non_field_errors": list(exc.messages)}
    raise ValidationDomainError("Les données fournies sont invalides.", details=details)


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


@transaction.atomic
def update_managed_depot(
    *,
    depot: Depot,
    data: dict,
    actor: User,
) -> Depot:
    """Met à jour les informations opérationnelles et horaires du dépôt géré par le responsable."""
    locked = Depot.objects.select_for_update().get(pk=depot.pk)
    assert_depot_editable(locked)

    allowed_direct_fields = (
        "name",
        "description",
        "address",
        "neighborhood",
        "phone",
        "opening_time",
        "closing_time",
    )

    before: dict = {}
    after: dict = {}
    updated_fields: list[str] = []

    for field in allowed_direct_fields:
        if field in data:
            old_val = getattr(locked, field)
            new_val = data[field]
            if old_val != new_val:
                before[field] = str(old_val)
                after[field] = str(new_val)
            setattr(locked, field, new_val)
            updated_fields.append(field)

    has_lat = "latitude" in data
    has_lng = "longitude" in data
    if has_lat != has_lng:
        raise ValidationDomainError(
            "Latitude et longitude doivent être fournies ensemble.",
            details={"coordinates": ["Fournissez latitude et longitude ensemble."]},
        )
    if has_lat and has_lng:
        new_lat = float(data["latitude"])
        new_lng = float(data["longitude"])
        before["location"] = {"lat": locked.latitude, "lng": locked.longitude}
        after["location"] = {"lat": new_lat, "lng": new_lng}
        locked.location = Point(new_lng, new_lat, srid=4326)
        updated_fields.append("location")

    try:
        locked.full_clean()
    except DjangoValidationError as exc:
        _raise_from_django_validation_error(exc)

    if updated_fields:
        locked.save(update_fields=[*set(updated_fields), "updated_at"])
        if before:
            record_audit_log(
                actor=actor,
                action="DEPOT_PROFILE_UPDATED",
                resource_type="Depot",
                resource_id=locked.pk,
                before_state=before,
                after_state=after,
            )

    return locked


def _sync_offer_operations(*, offer: DepotProductOffer, operations_data: list[dict]) -> None:
    """Remplace l'ensemble des opérations d'une offre avec validation stricte des prix."""
    seen_types: set[str] = set()
    to_create: list[OfferOperation] = []

    for entry in operations_data:
        op_type = entry["operation_type"]
        if op_type in seen_types:
            raise ValidationDomainError(
                "Type d'opération en double dans la requête.",
                details={"operations": [f"Opération {op_type} dupliquée."]},
            )
        seen_types.add(op_type)

        gas_price = entry["gas_price"]
        bottle_price = entry.get("bottle_price", 0)
        deposit_amount = entry.get("deposit_amount", 0)
        is_active = entry.get("is_active", True)

        if op_type != OperationType.FIRST_ACQUISITION and (bottle_price > 0 or deposit_amount > 0):
            raise ValidationDomainError(
                "Le prix de la bouteille et la consigne ne s'appliquent qu'à la Première bouteille.",
                details={
                    "operations": [
                        f"{op_type} ne peut pas comporter de prix bouteille ou consigne."
                    ]
                },
            )

        op = OfferOperation(
            offer=offer,
            operation_type=op_type,
            is_active=is_active,
            gas_price=gas_price,
            bottle_price=bottle_price,
            deposit_amount=deposit_amount,
        )
        try:
            op.full_clean(exclude=["offer"])
        except DjangoValidationError as exc:
            _raise_from_django_validation_error(exc)
        to_create.append(op)

    offer.operations.all().delete()
    if to_create:
        OfferOperation.objects.bulk_create(to_create)


def _sync_offer_exchange_brands(
    *,
    offer: DepotProductOffer,
    exchange_brand_ids: list[UUID],
) -> None:
    """Remplace les marques vides acceptées en échange sur l'offre."""
    unique_ids = list(dict.fromkeys(exchange_brand_ids))
    if not unique_ids:
        offer.exchange_brands.all().delete()
        return

    brands_by_id = {
        b.pk: b for b in Brand.objects.filter(pk__in=unique_ids, is_active=True)
    }
    missing = [str(bid) for bid in unique_ids if bid not in brands_by_id]
    if missing:
        raise ValidationDomainError(
            "Une ou plusieurs marques d'échange sont introuvables ou inactives.",
            details={"exchange_brand_ids": missing},
        )

    for bid in unique_ids:
        if bid == offer.product.brand_id:
            raise ValidationDomainError(
                "Une bouteille de même marque relève de la Recharge, pas de l'Échange.",
                details={
                    "exchange_brand_ids": [
                        "Impossible d'ajouter la marque du produit en marque d'échange."
                    ]
                },
            )

    offer.exchange_brands.all().delete()
    OfferExchangeBrand.objects.bulk_create(
        [OfferExchangeBrand(offer=offer, accepted_brand=brands_by_id[bid]) for bid in unique_ids]
    )


@transaction.atomic
def create_depot_offer(
    *,
    depot: Depot,
    product: Product,
    is_active: bool = True,
    notes: str = "",
    operations: list[dict] | None = None,
    exchange_brand_ids: list[UUID] | None = None,
) -> DepotProductOffer:
    """Crée une offre produit pour le dépôt avec ses opérations et marques d'échange."""
    locked_depot = Depot.objects.select_for_update().get(pk=depot.pk)
    assert_depot_editable(locked_depot)

    if product.status != ProductStatus.PUBLISHED or not product.brand.is_active:
        raise ValidationDomainError(
            "Seuls les produits publiés d'une marque active peuvent être commercialisés.",
            details={"product_id": ["Produit non disponible au catalogue public."]},
        )

    try:
        with transaction.atomic():
            offer = DepotProductOffer.objects.create(
                depot=locked_depot,
                product=product,
                is_active=is_active,
                notes=notes.strip() if notes else "",
            )
    except IntegrityError as exc:
        raise ConflictDomainError(
            "Ce produit est déjà présent dans les offres de votre dépôt.",
            code="OFFER_ALREADY_EXISTS",
        ) from exc

    if operations is not None:
        _sync_offer_operations(offer=offer, operations_data=operations)
    if exchange_brand_ids is not None:
        _sync_offer_exchange_brands(offer=offer, exchange_brand_ids=exchange_brand_ids)

    return offer


@transaction.atomic
def update_depot_offer(
    *,
    depot: Depot,
    offer_id: UUID,
    data: dict,
) -> DepotProductOffer:
    """Met à jour une offre appartenant exclusivement au dépôt (404 sinon)."""
    locked_depot = Depot.objects.select_for_update().get(pk=depot.pk)
    offer = (
        DepotProductOffer.objects.select_for_update()
        .select_related("product", "product__brand")
        .filter(pk=offer_id, depot=locked_depot)
        .first()
    )
    if offer is None:
        raise NotFoundDomainError("Offre introuvable.", code="NOT_FOUND")

    assert_depot_editable(locked_depot)

    updated_fields: list[str] = []
    if "is_active" in data:
        offer.is_active = bool(data["is_active"])
        updated_fields.append("is_active")
    if "notes" in data:
        offer.notes = (data["notes"] or "").strip()
        updated_fields.append("notes")

    if updated_fields:
        offer.save(update_fields=[*updated_fields, "updated_at"])

    if "operations" in data and data["operations"] is not None:
        _sync_offer_operations(offer=offer, operations_data=data["operations"])
    if "exchange_brand_ids" in data and data["exchange_brand_ids"] is not None:
        _sync_offer_exchange_brands(offer=offer, exchange_brand_ids=data["exchange_brand_ids"])

    return offer


@transaction.atomic
def delete_depot_offer(*, depot: Depot, offer_id: UUID) -> None:
    """Supprime une offre appartenant exclusivement au dépôt (404 sinon)."""
    locked_depot = Depot.objects.select_for_update().get(pk=depot.pk)
    offer = (
        DepotProductOffer.objects.select_for_update()
        .filter(pk=offer_id, depot=locked_depot)
        .first()
    )
    if offer is None:
        raise NotFoundDomainError("Offre introuvable.", code="NOT_FOUND")

    assert_depot_editable(locked_depot)
    offer.delete()


@transaction.atomic
def create_depot_product_proposal(
    *,
    depot: Depot,
    proposed_brand_name: str,
    capacity_kg: Decimal,
    product_type: str,
    name: str,
    description: str = "",
) -> ProductProposal:
    """Crée une proposition de produit soumise à validation admin (statut PENDING)."""
    locked_depot = Depot.objects.select_for_update().get(pk=depot.pk)
    assert_depot_editable(locked_depot)

    proposal = ProductProposal(
        depot=locked_depot,
        proposed_brand_name=proposed_brand_name,
        capacity_kg=capacity_kg,
        product_type=product_type,
        name=name,
        description=(description or "").strip(),
    )
    try:
        proposal.full_clean()
    except DjangoValidationError as exc:
        _raise_from_django_validation_error(exc)

    proposal.save()
    return proposal
