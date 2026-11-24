"""Services atomiques de gestion des stocks avec verrouillage SQL et journalisation immuable."""

from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.catalog.models import Product, ProductStatus
from apps.core.exceptions import (
    ConflictDomainError,
    ForbiddenDomainError,
    ValidationDomainError,
)
from apps.depots.models import Depot, DepotStatus, OperationType
from apps.inventory.models import (
    DepotStock,
    StockCategory,
    StockMovement,
    StockMovementType,
    StockReservation,
    StockReservationStatus,
)

EDITABLE_DEPOT_STATUSES = frozenset({DepotStatus.PENDING, DepotStatus.ACTIVE})
VALID_CATEGORIES = frozenset(StockCategory.values)
ADJUSTMENT_MOVEMENT_TYPES = frozenset(
    {StockMovementType.INVENTORY_CORRECTION, StockMovementType.MANUAL_ADJUSTMENT}
)
MAX_STOCK_QUANTITY = 2_147_483_647


def assert_depot_editable(depot: Depot) -> None:
    """Interdit toute mutation de stock/offres/infos lorsque le dépôt est suspendu ou désactivé."""
    if depot.status not in EDITABLE_DEPOT_STATUSES:
        raise ForbiddenDomainError(
            "Ce dépôt ne peut pas être modifié dans son statut actuel.",
            code="DEPOT_NOT_EDITABLE",
            details={"status": depot.status},
        )


def _validate_stock_target(*, product: Product, category: str) -> None:
    if category not in VALID_CATEGORIES:
        raise ValidationDomainError(
            "Catégorie de stock invalide.",
            details={"category": ["Catégorie non reconnue."]},
        )
    if product.status != ProductStatus.PUBLISHED or not product.brand.is_active:
        raise ValidationDomainError(
            "Seuls les produits publiés d'une marque active peuvent être gérés en stock.",
            details={"product": ["Produit non disponible au catalogue public."]},
        )


def _get_or_create_locked_stock(
    *,
    depot: Depot,
    product: Product,
    category: str,
) -> DepotStock:
    """Récupère et verrouille (FOR UPDATE) la ligne de stock, en la créant si absente."""
    stock = (
        DepotStock.objects.select_for_update()
        .filter(depot=depot, product=product, category=category)
        .first()
    )
    if stock is not None:
        return stock

    try:
        with transaction.atomic():
            DepotStock.objects.create(
                depot=depot,
                product=product,
                category=category,
                physical_quantity=0,
                reserved_quantity=0,
            )
    except IntegrityError:
        pass

    return DepotStock.objects.select_for_update().get(
        depot=depot,
        product=product,
        category=category,
    )


@transaction.atomic
def restock_depot_stock(
    *,
    depot: Depot,
    product: Product,
    category: str,
    quantity: int,
    actor: User,
    reason: str = "",
) -> tuple[DepotStock, StockMovement]:
    """Ajoute des bouteilles au stock physique (approvisionnement) avec trace immuable."""
    locked_depot = Depot.objects.select_for_update().get(pk=depot.pk)
    assert_depot_editable(locked_depot)
    _validate_stock_target(product=product, category=category)

    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity <= 0
        or quantity > MAX_STOCK_QUANTITY
    ):
        raise ValidationDomainError(
            "La quantité d'approvisionnement doit être un entier strictement positif valide.",
            details={"quantity": [f"Doit être compris entre 1 et {MAX_STOCK_QUANTITY}."]},
        )

    stock = _get_or_create_locked_stock(depot=locked_depot, product=product, category=category)
    before = stock.physical_quantity
    after = before + quantity
    if after > MAX_STOCK_QUANTITY:
        raise ValidationDomainError(
            "Le stock physique maximal autorisé serait dépassé.",
            details={"quantity": [f"Le stock total ne peut pas dépasser {MAX_STOCK_QUANTITY}."]},
        )
    stock.physical_quantity = after
    stock.save(update_fields=["physical_quantity", "updated_at"])

    movement = StockMovement.objects.create(
        depot=locked_depot,
        product=product,
        category=category,
        movement_type=StockMovementType.RESTOCK,
        quantity_before=before,
        quantity_after=after,
        delta=quantity,
        reason=reason.strip() if reason else "",
        actor=actor,
    )
    return stock, movement


@transaction.atomic
def adjust_depot_stock(
    *,
    depot: Depot,
    product: Product,
    category: str,
    new_physical_quantity: int,
    actor: User,
    reason: str,
    movement_type: str = StockMovementType.INVENTORY_CORRECTION,
    expected_physical_quantity: int | None = None,
) -> tuple[DepotStock, StockMovement]:
    """Corrige manuellement le stock physique (inventaire / ajustement) avec motif obligatoire."""
    locked_depot = Depot.objects.select_for_update().get(pk=depot.pk)
    assert_depot_editable(locked_depot)
    _validate_stock_target(product=product, category=category)

    if movement_type not in ADJUSTMENT_MOVEMENT_TYPES:
        raise ValidationDomainError(
            "Type de mouvement d'ajustement invalide.",
            details={"movement_type": ["Utilisez INVENTORY_CORRECTION ou MANUAL_ADJUSTMENT."]},
        )

    if not reason or not reason.strip():
        raise ValidationDomainError(
            "Un motif est obligatoire pour corriger un stock.",
            details={"reason": ["Ce champ est obligatoire."]},
        )

    if (
        isinstance(new_physical_quantity, bool)
        or not isinstance(new_physical_quantity, int)
        or new_physical_quantity < 0
        or new_physical_quantity > MAX_STOCK_QUANTITY
    ):
        raise ValidationDomainError(
            "La nouvelle quantité physique doit être un entier valide.",
            details={"new_physical_quantity": [f"Doit être compris entre 0 et {MAX_STOCK_QUANTITY}."]},
        )

    stock = _get_or_create_locked_stock(depot=locked_depot, product=product, category=category)

    if (
        expected_physical_quantity is not None
        and stock.physical_quantity != expected_physical_quantity
    ):
        raise ConflictDomainError(
            "Le stock a changé entre-temps. Vérifiez les chiffres et réessayez.",
            code="STOCK_CONFLICT",
            details={"current_physical_quantity": stock.physical_quantity},
        )

    if new_physical_quantity < stock.reserved_quantity:
        raise ConflictDomainError(
            "La quantité physique ne peut pas être inférieure à la quantité réservée.",
            code="STOCK_BELOW_RESERVED",
            details={"reserved_quantity": stock.reserved_quantity},
        )

    if new_physical_quantity == stock.physical_quantity:
        raise ConflictDomainError(
            "La quantité saisie est identique au stock actuel.",
            code="STOCK_UNCHANGED",
        )

    before = stock.physical_quantity
    delta = new_physical_quantity - before
    stock.physical_quantity = new_physical_quantity
    stock.save(update_fields=["physical_quantity", "updated_at"])

    movement = StockMovement.objects.create(
        depot=locked_depot,
        product=product,
        category=category,
        movement_type=movement_type,
        quantity_before=before,
        quantity_after=new_physical_quantity,
        delta=delta,
        reason=reason.strip(),
        actor=actor,
    )
    return stock, movement


@transaction.atomic
def scrap_depot_stock(
    *,
    depot: Depot,
    product: Product,
    category: str,
    quantity: int,
    actor: User,
    reason: str,
) -> tuple[DepotStock, StockMovement]:
    """Retire des bouteilles endommagées/mises au rebut avec motif obligatoire et garde-fou réservé."""
    locked_depot = Depot.objects.select_for_update().get(pk=depot.pk)
    assert_depot_editable(locked_depot)
    _validate_stock_target(product=product, category=category)

    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValidationDomainError(
            "La quantité mise au rebut doit être un entier strictement positif.",
            details={"quantity": ["Doit être supérieur à 0."]},
        )

    if not reason or not reason.strip():
        raise ValidationDomainError(
            "Un motif est obligatoire pour une mise au rebut.",
            details={"reason": ["Ce champ est obligatoire."]},
        )

    stock = _get_or_create_locked_stock(depot=locked_depot, product=product, category=category)
    before = stock.physical_quantity
    after = before - quantity

    if after < 0 or after < stock.reserved_quantity:
        raise ConflictDomainError(
            "Stock disponible insuffisant pour cette mise au rebut.",
            code="INSUFFICIENT_STOCK_FOR_SCRAP",
            details={
                "physical_quantity": before,
                "reserved_quantity": stock.reserved_quantity,
            },
        )

    stock.physical_quantity = after
    stock.save(update_fields=["physical_quantity", "updated_at"])

    movement = StockMovement.objects.create(
        depot=locked_depot,
        product=product,
        category=category,
        movement_type=StockMovementType.SCRAP,
        quantity_before=before,
        quantity_after=after,
        delta=-quantity,
        reason=reason.strip(),
        actor=actor,
    )
    return stock, movement


@transaction.atomic
def reserve_stock_for_order(
    *,
    order,
    depot: Depot,
    product: Product,
    operation_type: str,
    quantity: int,
    expires_at: datetime,
    actor: User | None = None,
) -> StockReservation:
    """Réserve atomiquement le stock pour une commande (verrou SQL FOR UPDATE, CDC §6.3, §6.7)."""
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity <= 0
        or quantity > MAX_STOCK_QUANTITY
    ):
        raise ValidationDomainError(
            "La quantité à réserver doit être un entier strictement positif.",
            details={"quantity": [f"Doit être compris entre 1 et {MAX_STOCK_QUANTITY}."]},
        )

    if operation_type == OperationType.FIRST_ACQUISITION:
        candidate_categories = [StockCategory.FULL, StockCategory.NEW]
        preference_order = [StockCategory.NEW, StockCategory.FULL]
    elif operation_type in {OperationType.REFILL, OperationType.EXCHANGE}:
        candidate_categories = [StockCategory.FULL]
        preference_order = [StockCategory.FULL]
    else:
        raise ValidationDomainError(
            "Type d'opération invalide pour la réservation de stock.",
            details={"operation_type": ["Opération non reconnue."]},
        )

    # Verrouillage déterministe (ordre alphabétique de category) pour éliminer tout deadlock
    locked_rows = list(
        DepotStock.objects.select_for_update()
        .filter(depot=depot, product=product, category__in=candidate_categories)
        .order_by("category", "id")
    )
    rows_by_cat = {row.category: row for row in locked_rows}

    chosen: DepotStock | None = None
    max_available = 0
    for cat in preference_order:
        row = rows_by_cat.get(cat)
        if row is not None:
            avail = row.available_quantity
            max_available = max(max_available, avail)
            if avail >= quantity and chosen is None:
                chosen = row

    if chosen is None:
        raise ConflictDomainError(
            "Stock disponible insuffisant pour cette commande.",
            code="INSUFFICIENT_STOCK",
            details={
                "requested_quantity": quantity,
                "available_quantity": max_available,
            },
        )

    avail_before = chosen.available_quantity
    avail_after = avail_before - quantity
    chosen.reserved_quantity += quantity
    chosen.save(update_fields=["reserved_quantity", "updated_at"])

    reservation = StockReservation.objects.create(
        stock=chosen,
        order=order,
        quantity=quantity,
        status=StockReservationStatus.ACTIVE,
        expires_at=expires_at,
    )
    StockMovement.objects.create(
        depot=depot,
        product=product,
        category=chosen.category,
        movement_type=StockMovementType.RESERVATION,
        quantity_before=avail_before,
        quantity_after=avail_after,
        delta=-quantity,
        reason=f"Réservation commande {order.reference}",
        actor=actor,
    )
    return reservation


@transaction.atomic
def release_order_reservations(
    *,
    order,
    actor: User | None = None,
    reason: str = "",
) -> list[StockReservation]:
    """Libère de façon idempotente toutes les réservations actives d'une commande (CDC §6.7)."""
    active_reservations = list(
        StockReservation.objects.select_for_update()
        .filter(order=order, status=StockReservationStatus.ACTIVE)
        .order_by("stock_id", "id")
    )
    if not active_reservations:
        return []

    stock_ids = sorted({res.stock_id for res in active_reservations})
    stocks_by_id = {
        s.pk: s
        for s in DepotStock.objects.select_for_update()
        .filter(pk__in=stock_ids)
        .order_by("id")
    }

    now = timezone.now()
    movement_reason = reason.strip() if reason else f"Libération commande {order.reference}"

    for res in active_reservations:
        stock = stocks_by_id[res.stock_id]
        avail_before = stock.available_quantity
        stock.reserved_quantity = max(0, stock.reserved_quantity - res.quantity)
        avail_after = stock.available_quantity
        stock.save(update_fields=["reserved_quantity", "updated_at"])

        res.status = StockReservationStatus.RELEASED
        res.released_at = now
        res.save(update_fields=["status", "released_at", "updated_at"])

        StockMovement.objects.create(
            depot_id=stock.depot_id,
            product_id=stock.product_id,
            category=stock.category,
            movement_type=StockMovementType.RELEASE,
            quantity_before=avail_before,
            quantity_after=avail_after,
            delta=avail_after - avail_before,
            reason=movement_reason,
            actor=actor,
        )

    return active_reservations


@transaction.atomic
def commit_order_pickup(
    *,
    order,
    actor: User,
    empty_return_product: Product | None = None,
    empty_return_quantity: int = 0,
    empty_return_reason: str = "",
) -> list[StockReservation]:
    """Consomme les réservations au retrait (physique & réservé -) et crédite les vides retournées."""
    active_reservations = list(
        StockReservation.objects.select_for_update()
        .filter(order=order, status=StockReservationStatus.ACTIVE)
        .order_by("stock_id", "id")
    )
    if not active_reservations:
        raise ConflictDomainError(
            "Aucune réservation active associée à cette commande.",
            code="NO_ACTIVE_RESERVATION",
        )

    empty_stock_id = None
    if empty_return_product is not None and empty_return_quantity > 0:
        empty_stock = _get_or_create_locked_stock(
            depot=order.depot,
            product=empty_return_product,
            category=StockCategory.EMPTY,
        )
        empty_stock_id = empty_stock.pk

    stock_ids = sorted(
        {res.stock_id for res in active_reservations}
        | ({empty_stock_id} if empty_stock_id is not None else set())
    )
    stocks_by_id = {
        s.pk: s
        for s in DepotStock.objects.select_for_update()
        .filter(pk__in=stock_ids)
        .order_by("id")
    }

    now = timezone.now()
    for res in active_reservations:
        stock = stocks_by_id[res.stock_id]
        phys_before = stock.physical_quantity
        phys_after = phys_before - res.quantity
        if phys_after < 0 or stock.reserved_quantity < res.quantity:
            raise ConflictDomainError(
                "Incohérence de stock lors de la validation du retrait.",
                code="INSUFFICIENT_STOCK",
            )
        stock.physical_quantity = phys_after
        stock.reserved_quantity -= res.quantity
        stock.save(update_fields=["physical_quantity", "reserved_quantity", "updated_at"])

        res.status = StockReservationStatus.CONSUMED
        res.consumed_at = now
        res.save(update_fields=["status", "consumed_at", "updated_at"])

        StockMovement.objects.create(
            depot_id=stock.depot_id,
            product_id=stock.product_id,
            category=stock.category,
            movement_type=StockMovementType.PICKUP_OUT,
            quantity_before=phys_before,
            quantity_after=phys_after,
            delta=-res.quantity,
            reason=f"Retrait commande {order.reference}",
            actor=actor,
        )

    if empty_stock_id is not None and empty_return_quantity > 0:
        empty_stock = stocks_by_id[empty_stock_id]
        empty_before = empty_stock.physical_quantity
        empty_after = empty_before + empty_return_quantity
        if empty_after > MAX_STOCK_QUANTITY:
            raise ValidationDomainError(
                "Le stock maximal de bouteilles vides serait dépassé.",
                details={"quantity": [f"Le stock ne peut pas dépasser {MAX_STOCK_QUANTITY}."]},
            )
        empty_stock.physical_quantity = empty_after
        empty_stock.save(update_fields=["physical_quantity", "updated_at"])

        StockMovement.objects.create(
            depot_id=empty_stock.depot_id,
            product_id=empty_stock.product_id,
            category=StockCategory.EMPTY,
            movement_type=StockMovementType.EMPTY_RETURN,
            quantity_before=empty_before,
            quantity_after=empty_after,
            delta=empty_return_quantity,
            reason=empty_return_reason.strip()
            if empty_return_reason
            else f"Retour bouteille vide commande {order.reference}",
            actor=actor,
        )

    return active_reservations
