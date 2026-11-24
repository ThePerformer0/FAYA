"""Fabriques inventory : lignes de stock et mouvements."""
from apps.inventory.models import DepotStock, StockCategory, StockMovement, StockMovementType
from tests.factories_catalog import make_product
from tests.factories_depots import make_depot


def make_stock(
    *,
    depot=None,
    product=None,
    category=StockCategory.FULL,
    physical_quantity=10,
    reserved_quantity=0,
    **extra,
):
    """Ligne de stock (10 en physique / 0 réservé par défaut, plus utile que 0/0 pour les tests)."""
    return DepotStock.objects.create(
        depot=depot if depot is not None else make_depot(),
        product=product if product is not None else make_product(),
        category=category,
        physical_quantity=physical_quantity,
        reserved_quantity=reserved_quantity,
        **extra,
    )


def make_movement(
    *,
    depot=None,
    product=None,
    category=StockCategory.FULL,
    movement_type=StockMovementType.RESTOCK,
    quantity_before=0,
    delta=5,
    quantity_after=None,
    reason="",
    actor=None,
    **extra,
):
    """Mouvement cohérent par défaut : quantity_after = quantity_before + delta.

    Passer explicitement `quantity_after` permet de fabriquer un mouvement incohérent
    (pour tester les contraintes SQL).
    """
    if quantity_after is None:
        quantity_after = quantity_before + delta
    return StockMovement.objects.create(
        depot=depot if depot is not None else make_depot(),
        product=product if product is not None else make_product(),
        category=category,
        movement_type=movement_type,
        quantity_before=quantity_before,
        quantity_after=quantity_after,
        delta=delta,
        reason=reason,
        actor=actor,
        **extra,
    )
