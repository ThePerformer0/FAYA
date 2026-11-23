"""Modèles des dépôts de gaz, de leurs offres commerciales et opérations (CDC §2, §4, §5)."""

from django.conf import settings
from django.contrib.gis.db import models as gis_models
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.accounts.models import UserRole, phone_e164_validator
from apps.catalog.models import Brand, Product
from apps.core.models import TimeStampedUUIDModel


class DepotStatus(models.TextChoices):
    PENDING = "PENDING", "En attente de validation"
    ACTIVE = "ACTIVE", "Actif"
    SUSPENDED = "SUSPENDED", "Suspendu"
    DISABLED = "DISABLED", "Désactivé"


class Depot(TimeStampedUUIDModel):
    """Dépôt de gaz géré par un unique responsable (ADR-02, ADR-11)."""

    manager = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="managed_depot",
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    address = models.CharField(max_length=255)
    neighborhood = models.CharField(
        max_length=120,
        blank=True,
        default="",
        db_index=True,
        help_text="Quartier ou zone de référence pour la recherche textuelle.",
    )
    phone = models.CharField(
        max_length=20,
        validators=[phone_e164_validator],
        help_text="Numéro de contact affiché sur la fiche publique (format E.164).",
    )
    location = gis_models.PointField(
        srid=4326,
        geography=True,
        spatial_index=True,
        help_text="Position GPS WGS84 (longitude, latitude).",
    )
    opening_time = models.TimeField()
    closing_time = models.TimeField()
    status = models.CharField(
        max_length=20,
        choices=DepotStatus.choices,
        default=DepotStatus.PENDING,
        db_index=True,
    )

    class Meta:
        verbose_name = "Dépôt"
        verbose_name_plural = "Dépôts"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=Q(closing_time__gt=F("opening_time")),
                name="depots_depot_closing_after_opening",
            ),
            models.CheckConstraint(
                condition=~Q(name=""),
                name="depots_depot_name_not_empty",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "opening_time", "closing_time"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_status_display()})"

    def save(self, *args, **kwargs) -> None:
        if self.name:
            self.name = self.name.strip()
        if self.address:
            self.address = self.address.strip()
        if self.neighborhood:
            self.neighborhood = self.neighborhood.strip()
        if self.phone:
            self.phone = self.phone.strip()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}

        if self.opening_time and self.closing_time and self.closing_time <= self.opening_time:
            errors["closing_time"] = "L'heure de fermeture doit être postérieure à l'ouverture."

        if self.manager_id and self.manager.role != UserRole.DEPOT_MANAGER:
            errors["manager"] = (
                "Le compte associé doit avoir le rôle Responsable de dépôt (DEPOT_MANAGER)."
            )

        if errors:
            raise ValidationError(errors)

    @property
    def latitude(self) -> float:
        return float(self.location.y)

    @property
    def longitude(self) -> float:
        return float(self.location.x)


class DepotProductOffer(TimeStampedUUIDModel):
    """Commercialisation d'un produit du catalogue central par un dépôt (CDC §4.2)."""

    depot = models.ForeignKey(
        Depot,
        on_delete=models.CASCADE,
        related_name="offers",
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="depot_offers",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Offre produit d'un dépôt"
        verbose_name_plural = "Offres produits des dépôts"
        ordering = ["product__brand__name", "product__capacity_kg"]
        constraints = [
            models.UniqueConstraint(
                fields=["depot", "product"],
                name="depots_offer_unique_depot_product",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.depot.name} — {self.product}"


class OperationType(models.TextChoices):
    REFILL = "REFILL", "Recharge"
    EXCHANGE = "EXCHANGE", "Échange"
    FIRST_ACQUISITION = "FIRST_ACQUISITION", "Première bouteille"


class OfferOperation(TimeStampedUUIDModel):
    """Opération activée sur une offre avec décomposition transparente des prix (CDC §5)."""

    offer = models.ForeignKey(
        DepotProductOffer,
        on_delete=models.CASCADE,
        related_name="operations",
    )
    operation_type = models.CharField(
        max_length=24,
        choices=OperationType.choices,
    )
    is_active = models.BooleanField(default=True)
    gas_price = models.PositiveIntegerField(
        help_text="Prix de l'opération ou du gaz (en FCFA).",
    )
    bottle_price = models.PositiveIntegerField(
        default=0,
        help_text="Prix de la bouteille (Première bouteille uniquement, en FCFA).",
    )
    deposit_amount = models.PositiveIntegerField(
        default=0,
        help_text="Montant de la consigne (Première bouteille uniquement, en FCFA).",
    )

    class Meta:
        verbose_name = "Opération d'offre"
        verbose_name_plural = "Opérations d'offres"
        ordering = ["operation_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["offer", "operation_type"],
                name="depots_offerop_unique_type",
            ),
            models.CheckConstraint(
                condition=Q(operation_type=OperationType.FIRST_ACQUISITION)
                | (Q(bottle_price=0) & Q(deposit_amount=0)),
                name="depots_offerop_bottle_deposit_only_first_acq",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.offer} · {self.get_operation_type_display()} ({self.total_unit_price} FCFA)"

    def clean(self) -> None:
        super().clean()
        if self.operation_type != OperationType.FIRST_ACQUISITION and (
            self.bottle_price > 0 or self.deposit_amount > 0
        ):
            raise ValidationError(
                "Le prix de la bouteille et la consigne ne s'appliquent qu'à la Première bouteille."
            )

    @property
    def total_unit_price(self) -> int:
        return int(self.gas_price + self.bottle_price + self.deposit_amount)


class OfferExchangeBrand(TimeStampedUUIDModel):
    """Marque de bouteille vide acceptée en échange sur une offre (CDC §4.2, §5.2)."""

    offer = models.ForeignKey(
        DepotProductOffer,
        on_delete=models.CASCADE,
        related_name="exchange_brands",
    )
    accepted_brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="accepted_in_offers",
    )

    class Meta:
        verbose_name = "Marque acceptée en échange"
        verbose_name_plural = "Marques acceptées en échange"
        ordering = ["accepted_brand__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["offer", "accepted_brand"],
                name="depots_exchangebrand_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.offer} ← vide {self.accepted_brand.name}"

    def clean(self) -> None:
        super().clean()
        if (
            self.offer_id
            and self.accepted_brand_id
            and self.accepted_brand_id == self.offer.product.brand_id
        ):
            raise ValidationError(
                {
                    "accepted_brand": (
                        "Une bouteille de même marque relève de la Recharge, pas de l'Échange."
                    )
                }
            )
