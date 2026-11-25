"""Modèles du cycle de commande, lignes figées, historique immuable et paiements (CDC §7, §8)."""

import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import TimeStampedUUIDModel
from apps.depots.models import OperationType

_REFERENCE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def generate_order_reference() -> str:
    """Génère une référence courte et lisible pour le retrait au comptoir (ex. FAY-7K9P2M)."""
    code = "".join(secrets.choice(_REFERENCE_ALPHABET) for _ in range(6))
    return f"FAY-{code}"


class OrderStatus(models.TextChoices):
    PENDING = "PENDING", "En attente"
    CONFIRMED = "CONFIRMED", "Confirmée"
    PICKED_UP = "PICKED_UP", "Retirée"
    REFUSED = "REFUSED", "Refusée"
    EXPIRED = "EXPIRED", "Expirée"
    CANCELLED = "CANCELLED", "Annulée"


ACTIVE_ORDER_STATUSES = frozenset({OrderStatus.PENDING, OrderStatus.CONFIRMED})
FINAL_ORDER_STATUSES = frozenset(
    {
        OrderStatus.PICKED_UP,
        OrderStatus.REFUSED,
        OrderStatus.EXPIRED,
        OrderStatus.CANCELLED,
    }
)


class PaymentMethod(models.TextChoices):
    CASH = "CASH", "Espèces"
    MOBILE_MONEY = "MOBILE_MONEY", "Mobile Money"


class PaymentStatus(models.TextChoices):
    PENDING = "PENDING", "En attente"
    PAID = "PAID", "Payé"


class OrderCancellationSource(models.TextChoices):
    CUSTOMER = "CUSTOMER", "Client"
    DEPOT_NON_CONFORMITY = "DEPOT_NON_CONFORMITY", "Non-conformité bouteille vide"
    SYSTEM = "SYSTEM", "Système"


class Order(TimeStampedUUIDModel):
    """Commande de retrait au dépôt (machine à 6 états, max 1 active par client)."""

    reference = models.CharField(
        max_length=24,
        unique=True,
        default=generate_order_reference,
        db_index=True,
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
    )
    depot = models.ForeignKey(
        "depots.Depot",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.PENDING,
        db_index=True,
    )
    payment_status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )
    total_amount = models.PositiveIntegerField(
        help_text="Montant total figé en FCFA au moment de la création.",
    )
    response_deadline_at = models.DateTimeField(db_index=True)
    pickup_deadline_at = models.DateTimeField(null=True, blank=True, db_index=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    refused_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    status_reason = models.TextField(blank=True, default="")
    cancellation_source = models.CharField(
        max_length=32,
        choices=OrderCancellationSource.choices,
        blank=True,
        default="",
    )
    counted_as_no_show = models.BooleanField(default=False, db_index=True)

    class Meta:
        verbose_name = "Commande"
        verbose_name_plural = "Commandes"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer"],
                condition=Q(status__in=[OrderStatus.PENDING, OrderStatus.CONFIRMED]),
                name="orders_unique_active_order_per_customer",
            ),
            models.CheckConstraint(
                condition=Q(total_amount__gte=0),
                name="orders_order_total_amount_gte_0",
            ),
            models.CheckConstraint(
                condition=~Q(status=OrderStatus.CONFIRMED) | Q(pickup_deadline_at__isnull=False),
                name="orders_confirmed_requires_pickup_deadline",
            ),
        ]
        indexes = [
            models.Index(fields=["customer", "-created_at"]),
            models.Index(fields=["depot", "status", "-created_at"]),
            models.Index(fields=["status", "response_deadline_at"]),
            models.Index(fields=["status", "pickup_deadline_at"]),
            models.Index(fields=["customer", "counted_as_no_show", "expired_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.reference} ({self.get_status_display()})"

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_ORDER_STATUSES


class OrderItem(TimeStampedUUIDModel):
    """Ligne de commande avec prix et libellés figés en instantané (1 ligne dans le MVP)."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    operation_type = models.CharField(
        max_length=32,
        choices=OperationType.choices,
    )
    exchange_brand = models.ForeignKey(
        "catalog.Brand",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="exchange_order_items",
    )
    quantity = models.PositiveSmallIntegerField()

    product_name_snapshot = models.CharField(max_length=150)
    brand_name_snapshot = models.CharField(max_length=100)
    capacity_kg_snapshot = models.DecimalField(max_digits=5, decimal_places=2)
    exchange_brand_name_snapshot = models.CharField(max_length=100, blank=True, default="")

    unit_gas_price = models.PositiveIntegerField()
    unit_bottle_price = models.PositiveIntegerField(default=0)
    unit_deposit_amount = models.PositiveIntegerField(default=0)
    unit_total_price = models.PositiveIntegerField()
    line_total_amount = models.PositiveIntegerField()

    class Meta:
        verbose_name = "Ligne de commande"
        verbose_name_plural = "Lignes de commande"
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="orders_item_quantity_gte_1",
            ),
            models.CheckConstraint(
                condition=Q(
                    unit_total_price=F("unit_gas_price")
                    + F("unit_bottle_price")
                    + F("unit_deposit_amount")
                ),
                name="orders_item_unit_total_consistent",
            ),
            models.CheckConstraint(
                condition=Q(line_total_amount=F("unit_total_price") * F("quantity")),
                name="orders_item_line_total_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(operation_type=OperationType.EXCHANGE) | Q(exchange_brand__isnull=False)
                ),
                name="orders_item_exchange_requires_brand",
            ),
            models.CheckConstraint(
                condition=(
                    Q(operation_type=OperationType.EXCHANGE) | Q(exchange_brand__isnull=True)
                ),
                name="orders_item_non_exchange_forbids_brand",
            ),
            models.CheckConstraint(
                condition=(
                    Q(operation_type=OperationType.FIRST_ACQUISITION)
                    | (Q(unit_bottle_price=0) & Q(unit_deposit_amount=0))
                ),
                name="orders_item_bottle_deposit_only_first_acq",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.quantity}× {self.brand_name_snapshot} {self.capacity_kg_snapshot} kg "
            f"[{self.operation_type}]"
        )

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}
        if self.quantity is None or self.quantity < 1:
            errors["quantity"] = "La quantité doit être supérieure ou égale à 1."
        if self.operation_type == OperationType.EXCHANGE and not self.exchange_brand_id:
            errors["exchange_brand"] = "La marque de la bouteille vide est requise pour un échange."
        if self.operation_type != OperationType.EXCHANGE and self.exchange_brand_id:
            errors["exchange_brand"] = "Une marque d'échange ne s'applique qu'à l'opération Échange."
        if self.operation_type != OperationType.FIRST_ACQUISITION and (
            (self.unit_bottle_price or 0) > 0 or (self.unit_deposit_amount or 0) > 0
        ):
            errors["unit_bottle_price"] = (
                "Le prix bouteille et la consigne ne s'appliquent qu'à la Première bouteille."
            )
        if errors:
            raise ValidationError(errors)


class ImmutableOrderStatusHistoryQuerySet(models.QuerySet):
    """Interdit toute modification, upsert ou suppression du journal de transitions."""

    def update(self, **kwargs):
        raise PermissionError(
            "L'historique des statuts de commande est immuable : modification interdite."
        )

    def delete(self):
        raise PermissionError(
            "L'historique des statuts de commande est immuable : suppression interdite."
        )

    def bulk_update(self, objs, fields, batch_size=None):
        raise PermissionError(
            "L'historique des statuts de commande est immuable : modification en masse interdite."
        )

    def bulk_create(self, objs, *args, update_conflicts=False, **kwargs):
        if update_conflicts:
            raise PermissionError(
                "L'historique des statuts de commande est immuable : upsert interdit."
            )
        return super().bulk_create(objs, *args, update_conflicts=False, **kwargs)


class OrderStatusHistory(models.Model):
    """Journal immuable de toutes les transitions de statut d'une commande."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="status_history",
    )
    from_status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        blank=True,
        default="",
    )
    to_status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_status_changes",
    )
    reason = models.TextField(blank=True, default="")
    sequence = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = ImmutableOrderStatusHistoryQuerySet.as_manager()

    class Meta:
        verbose_name = "Historique de statut commande"
        verbose_name_plural = "Historiques de statut commande"
        ordering = ["sequence", "created_at", "id"]
        indexes = [
            models.Index(fields=["order", "sequence", "created_at"]),
        ]

    def __str__(self) -> str:
        origin = self.from_status or "NEW"
        return f"{self.order.reference} : {origin} -> {self.to_status}"

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise PermissionError(
                "L'historique des statuts de commande est immuable : modification interdite."
            )
        if not self.sequence and self.order_id:
            last_seq = (
                OrderStatusHistory.objects.filter(order_id=self.order_id)
                .order_by("-sequence")
                .values_list("sequence", flat=True)
                .first()
            )
            self.sequence = (last_seq or 0) + 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError(
            "L'historique des statuts de commande est immuable : suppression interdite."
        )


class PaymentRecord(TimeStampedUUIDModel):
    """Enregistrement déclaratif du paiement effectué au comptoir lors du retrait (CDC §8)."""

    order = models.OneToOneField(
        Order,
        on_delete=models.PROTECT,
        related_name="payment_record",
    )
    expected_amount = models.PositiveIntegerField()
    received_amount = models.PositiveIntegerField()
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
    )
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PAID,
    )
    external_reference = models.CharField(max_length=120, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_payments",
    )
    paid_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "Paiement au dépôt"
        verbose_name_plural = "Paiements au dépôt"
        ordering = ["-paid_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(expected_amount__gte=0),
                name="orders_payment_expected_gte_0",
            ),
            models.CheckConstraint(
                condition=Q(received_amount__gte=0),
                name="orders_payment_received_gte_0",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.order.reference} · {self.received_amount} FCFA ({self.payment_method})"
