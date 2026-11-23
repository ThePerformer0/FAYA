"""Modèles du catalogue central de référence et des propositions produits (CDC §4)."""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q, Value
from django.db.models.functions import Lower, Trim
from django.db.models.lookups import Exact

from apps.core.models import TimeStampedUUIDModel


class Brand(TimeStampedUUIDModel):
    """Marque de bouteille de gaz du référentiel commun."""

    name = models.CharField(max_length=100, db_collation="und-x-icu")
    logo_url = models.URLField(blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "Marque"
        verbose_name_plural = "Marques"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="catalog_brand_unique_name_ci",
            ),
            models.CheckConstraint(
                condition=~Q(Exact(Trim("name"), Value(""))),
                name="catalog_brand_name_not_empty",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        if not self.name or not self.name.strip():
            raise ValidationError({"name": "Le nom de la marque est obligatoire."})

    def save(self, *args, **kwargs) -> None:
        if self.name:
            self.name = self.name.strip()
        super().save(*args, **kwargs)


class ProductType(models.TextChoices):
    BUTANE = "BUTANE", "Butane"
    PROPANE = "PROPANE", "Propane"
    LPG = "LPG", "GPL"


class ProductStatus(models.TextChoices):
    DRAFT = "DRAFT", "Brouillon"
    PUBLISHED = "PUBLISHED", "Publié"
    ARCHIVED = "ARCHIVED", "Archivé"


class Product(TimeStampedUUIDModel):
    """Produit de référence central (marque + capacité + type)."""

    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="products",
    )
    capacity_kg = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Capacité de la bouteille en kilogrammes (ex. 6.00, 12.50).",
    )
    product_type = models.CharField(
        max_length=20,
        choices=ProductType.choices,
        default=ProductType.BUTANE,
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    characteristics = models.JSONField(default=dict, blank=True)
    image_url = models.URLField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=ProductStatus.choices,
        default=ProductStatus.DRAFT,
        db_index=True,
    )

    class Meta:
        verbose_name = "Produit de référence"
        verbose_name_plural = "Produits de référence"
        ordering = ["brand__name", "capacity_kg", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "capacity_kg", "product_type"],
                name="catalog_product_unique_spec",
            ),
            models.CheckConstraint(
                condition=Q(capacity_kg__gt=Decimal("0")),
                name="catalog_product_capacity_gt_0",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "brand"]),
            models.Index(fields=["status", "capacity_kg"]),
        ]

    def __str__(self) -> str:
        return f"{self.brand.name} · {self.capacity_kg:g} kg ({self.get_product_type_display()})"

    def clean(self) -> None:
        super().clean()
        if not self.name or not self.name.strip():
            raise ValidationError({"name": "Le nom du produit est obligatoire."})

    def save(self, *args, **kwargs) -> None:
        if self.name:
            self.name = self.name.strip()
        super().save(*args, **kwargs)


class ProductProposalStatus(models.TextChoices):
    PENDING = "PENDING", "En attente"
    APPROVED = "APPROVED", "Approuvée"
    REJECTED = "REJECTED", "Refusée"


class ProductProposal(TimeStampedUUIDModel):
    """Produit supplémentaire proposé par un dépôt, soumis à validation admin (CDC §4.3)."""

    depot = models.ForeignKey(
        "depots.Depot",
        on_delete=models.CASCADE,
        related_name="product_proposals",
    )
    proposed_brand_name = models.CharField(max_length=100)
    capacity_kg = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    product_type = models.CharField(
        max_length=20,
        choices=ProductType.choices,
        default=ProductType.BUTANE,
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=ProductProposalStatus.choices,
        default=ProductProposalStatus.PENDING,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_product_proposals",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, default="")
    created_product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_proposals",
    )

    class Meta:
        verbose_name = "Proposition de produit"
        verbose_name_plural = "Propositions de produits"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(capacity_kg__gt=Decimal("0")),
                name="catalog_proposal_capacity_gt_0",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.proposed_brand_name} {self.capacity_kg:g} kg ({self.get_status_display()})"

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if not self.proposed_brand_name or not self.proposed_brand_name.strip():
            errors["proposed_brand_name"] = "Le nom de la marque est obligatoire."
        if not self.name or not self.name.strip():
            errors["name"] = "Le nom du produit est obligatoire."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs) -> None:
        if self.proposed_brand_name:
            self.proposed_brand_name = self.proposed_brand_name.strip()
        if self.name:
            self.name = self.name.strip()
        super().save(*args, **kwargs)
