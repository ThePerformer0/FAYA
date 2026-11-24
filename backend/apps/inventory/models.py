"""Modèles de gestion des stocks par catégorie et journal immuable des mouvements (CDC §6)."""

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.core.models import TimeStampedUUIDModel


class StockCategory(models.TextChoices):
    FULL = "FULL", "Pleine"
    EMPTY = "EMPTY", "Vide"
    NEW = "NEW", "Neuve"
    DEPOSIT = "DEPOSIT", "Sous consigne"


class StockMovementType(models.TextChoices):
    RESTOCK = "RESTOCK", "Approvisionnement"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT", "Ajustement manuel"
    INVENTORY_CORRECTION = "INVENTORY_CORRECTION", "Correction d'inventaire"
    SCRAP = "SCRAP", "Mise au rebut"
    RESERVATION = "RESERVATION", "Réservation"
    RELEASE = "RELEASE", "Libération"
    PICKUP_OUT = "PICKUP_OUT", "Remise client"
    EMPTY_RETURN = "EMPTY_RETURN", "Retour bouteille vide"


class DepotStock(TimeStampedUUIDModel):
    """Stock d'un dépôt pour un produit et une catégorie donnée (pleines, vides, neuves, consigne)."""

    depot = models.ForeignKey(
        "depots.Depot",
        on_delete=models.CASCADE,
        related_name="stocks",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="depot_stocks",
    )
    category = models.CharField(
        max_length=20,
        choices=StockCategory.choices,
        db_index=True,
    )
    physical_quantity = models.IntegerField(
        default=0,
        help_text="Quantité physique réellement présente au dépôt.",
    )
    reserved_quantity = models.IntegerField(
        default=0,
        help_text="Quantité réservée par des commandes actives (gérée par le système).",
    )

    class Meta:
        verbose_name = "Stock dépôt"
        verbose_name_plural = "Stocks dépôts"
        ordering = ["depot__name", "product__brand__name", "product__capacity_kg", "category"]
        constraints = [
            models.UniqueConstraint(
                fields=["depot", "product", "category"],
                name="inventory_stock_unique_depot_product_category",
            ),
            models.CheckConstraint(
                condition=Q(physical_quantity__gte=0),
                name="inventory_stock_physical_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(reserved_quantity__gte=0),
                name="inventory_stock_reserved_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(reserved_quantity__lte=F("physical_quantity")),
                name="inventory_stock_reserved_lte_physical",
            ),
            models.CheckConstraint(
                condition=~Q(category=StockCategory.EMPTY) | Q(reserved_quantity=0),
                name="inventory_stock_empty_never_reserved",
            ),
        ]
        indexes = [
            models.Index(fields=["depot", "product"]),
            models.Index(fields=["depot", "category"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.depot.name} — {self.product} [{self.get_category_display()}] : "
            f"{self.physical_quantity} (rés. {self.reserved_quantity})"
        )

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}

        if self.physical_quantity is None or self.physical_quantity < 0:
            errors["physical_quantity"] = "La quantité physique doit être supérieure ou égale à 0."

        if self.reserved_quantity is None or self.reserved_quantity < 0:
            errors["reserved_quantity"] = "La quantité réservée doit être supérieure ou égale à 0."

        if (
            self.physical_quantity is not None
            and self.reserved_quantity is not None
            and self.reserved_quantity > self.physical_quantity
        ):
            errors["reserved_quantity"] = (
                "La quantité réservée ne peut pas dépasser la quantité physique."
            )

        if self.category == StockCategory.EMPTY and self.reserved_quantity:
            errors["reserved_quantity"] = (
                "Les bouteilles vides ne peuvent jamais être réservées à la vente."
            )

        if errors:
            raise ValidationError(errors)

    @property
    def available_quantity(self) -> int:
        """Stock disponible à la vente : jamais les bouteilles vides (CDC §6.1)."""
        if self.category == StockCategory.EMPTY:
            return 0
        return int(self.physical_quantity - self.reserved_quantity)


class ImmutableStockMovementQuerySet(models.QuerySet):
    """Interdit toute modification, upsert ou suppression en masse du journal des mouvements."""

    def update(self, **kwargs):
        raise PermissionError(
            "Le journal des mouvements de stock est immuable : modification interdite."
        )

    def delete(self):
        raise PermissionError(
            "Le journal des mouvements de stock est immuable : suppression interdite."
        )

    def bulk_update(self, objs, fields, batch_size=None):
        raise PermissionError(
            "Le journal des mouvements de stock est immuable : modification en masse interdite."
        )

    def bulk_create(self, objs, *args, update_conflicts=False, **kwargs):
        if update_conflicts:
            raise PermissionError(
                "Le journal des mouvements de stock est immuable : upsert interdit."
            )
        return super().bulk_create(objs, *args, update_conflicts=False, **kwargs)


class StockMovement(models.Model):
    """Journal immuable de chaque variation de stock d'un dépôt (CDC §6.2)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    depot = models.ForeignKey(
        "depots.Depot",
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="stock_movements",
    )
    category = models.CharField(
        max_length=20,
        choices=StockCategory.choices,
    )
    movement_type = models.CharField(
        max_length=32,
        choices=StockMovementType.choices,
        db_index=True,
    )
    quantity_before = models.IntegerField()
    quantity_after = models.IntegerField()
    delta = models.IntegerField()
    reason = models.TextField(blank=True, default="")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = ImmutableStockMovementQuerySet.as_manager()

    class Meta:
        verbose_name = "Mouvement de stock"
        verbose_name_plural = "Mouvements de stock"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity_before__gte=0),
                name="inventory_movement_before_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(quantity_after__gte=0),
                name="inventory_movement_after_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(delta=F("quantity_after") - F("quantity_before")),
                name="inventory_movement_delta_consistent",
            ),
        ]
        indexes = [
            models.Index(fields=["depot", "-created_at"]),
            models.Index(fields=["depot", "product", "-created_at"]),
        ]

    def __str__(self) -> str:
        sign = "+" if self.delta > 0 else ""
        return (
            f"{self.depot.name} · {self.product} [{self.category}] "
            f"{self.movement_type} ({sign}{self.delta})"
        )

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise PermissionError(
                "Le journal des mouvements de stock est immuable : modification interdite."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError(
            "Le journal des mouvements de stock est immuable : suppression interdite."
        )
