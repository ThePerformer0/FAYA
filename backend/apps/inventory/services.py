"""Services atomiques de gestion des stocks avec verrouillage SQL et journalisation immuable."""

from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.catalog.models import Product, ProductStatus
from apps.core.exceptions import (
    ConflictDomainError,
    ForbiddenDomainError,
    ValidationDomainError,
)
from apps.depots.models import Depot, DepotStatus
from apps.inventory.models import (
    DepotStock,
    StockCategory,
    StockMovement,
    StockMovementType,
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
