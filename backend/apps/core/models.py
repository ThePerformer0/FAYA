"""Modèles transversaux : base UUID, paramètres globaux singleton et journal d'audit."""

import uuid
from zoneinfo import available_timezones

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


class TimeStampedUUIDModel(models.Model):
    """Classe de base abstraite pour les entités métier exposées via l'API."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PlatformSetting(models.Model):
    """Paramètres globaux de la plateforme (singleton id=1, CDC §2.4)."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    timezone = models.CharField(
        max_length=64,
        default="Africa/Abidjan",
        help_text="Fuseau horaire unique utilisé pour les horaires des dépôts.",
    )
    order_response_timeout_minutes = models.PositiveSmallIntegerField(
        default=15,
        help_text="Délai maximal de réponse du dépôt à une nouvelle commande (minutes).",
    )
    order_pickup_timeout_minutes = models.PositiveSmallIntegerField(
        default=120,
        help_text="Délai maximal de retrait après confirmation, borné à la fermeture (minutes).",
    )
    order_cutoff_before_close_minutes = models.PositiveSmallIntegerField(
        default=30,
        help_text="Arrêt des prises de commande avant la fermeture du dépôt (minutes).",
    )
    max_quantity_per_order = models.PositiveSmallIntegerField(
        default=3,
        help_text="Nombre maximal de bouteilles par commande.",
    )
    max_active_orders_per_customer = models.PositiveSmallIntegerField(
        default=1,
        help_text="Nombre maximal de commandes actives simultanées par client.",
    )
    no_show_threshold = models.PositiveSmallIntegerField(
        default=3,
        help_text="Nombre de retraits non effectués déclenchant une suspension.",
    )
    no_show_window_days = models.PositiveSmallIntegerField(
        default=30,
        help_text="Fenêtre glissante de comptage des retraits non effectués (jours).",
    )
    suspension_duration_days = models.PositiveSmallIntegerField(
        default=7,
        help_text="Durée de suspension après dépassement du seuil (jours).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Paramètres de la plateforme"
        verbose_name_plural = "Paramètres de la plateforme"
        constraints = [
            models.CheckConstraint(
                condition=Q(id=1),
                name="core_platformsetting_singleton_id_1",
            ),
            models.CheckConstraint(
                condition=Q(order_response_timeout_minutes__gt=0),
                name="core_platformsetting_response_timeout_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(order_pickup_timeout_minutes__gt=0),
                name="core_platformsetting_pickup_timeout_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(
                    order_cutoff_before_close_minutes__gte=F("order_response_timeout_minutes")
                ),
                name="core_platformsetting_cutoff_gte_response_timeout",
            ),
            models.CheckConstraint(
                condition=Q(max_quantity_per_order__gt=0),
                name="core_platformsetting_max_qty_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(max_active_orders_per_customer__gt=0),
                name="core_platformsetting_max_active_orders_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(no_show_threshold__gt=0),
                name="core_platformsetting_no_show_threshold_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(no_show_window_days__gt=0),
                name="core_platformsetting_no_show_window_gt_0",
            ),
            models.CheckConstraint(
                condition=Q(suspension_duration_days__gt=0),
                name="core_platformsetting_suspension_duration_gt_0",
            ),
        ]

    def __str__(self) -> str:
        return "Paramètres globaux Faya"

    def save(self, *args, **kwargs) -> None:
        self.pk = 1
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self) -> None:
        super().clean()
        errors: dict[str, str] = {}

        if not self.timezone or self.timezone not in available_timezones():
            errors["timezone"] = "Fuseau horaire IANA invalide."

        cutoff = self.order_cutoff_before_close_minutes
        timeout = self.order_response_timeout_minutes
        if isinstance(cutoff, int) and isinstance(timeout, int) and cutoff < timeout:
            errors["order_cutoff_before_close_minutes"] = (
                "L'arrêt des prises de commande avant la fermeture doit être "
                "supérieur ou égal au délai de réponse du dépôt."
            )

        if errors:
            raise ValidationError(errors)

    @classmethod
    def load(cls) -> "PlatformSetting":
        instance, _ = cls.objects.get_or_create(pk=1)
        return instance


class ImmutableAuditLogQuerySet(models.QuerySet):
    """Interdit toute modification ou suppression en masse du journal d'audit."""

    def update(self, **kwargs):
        raise PermissionError("Le journal d'audit est immuable : modification interdite.")

    def delete(self):
        raise PermissionError("Le journal d'audit est immuable : suppression interdite.")


class AuditLog(models.Model):
    """Journal immuable des opérations sensibles et administratives (CDC §13.6)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=100, db_index=True)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=64)
    before_state = models.JSONField(null=True, blank=True)
    after_state = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = ImmutableAuditLogQuerySet.as_manager()

    class Meta:
        verbose_name = "Journal d'audit"
        verbose_name_plural = "Journaux d'audit"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["resource_type", "resource_id"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} ({self.resource_type}:{self.resource_id})"

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise PermissionError("Le journal d'audit est immuable : modification interdite.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Le journal d'audit est immuable : suppression interdite.")
