"""Modèles d'identité, de rôles et de suspensions clients (CDC §3, §7.9, ADR-11)."""

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import TimeStampedUUIDModel

phone_e164_validator = RegexValidator(
    regex=r"^\+[1-9][0-9]{7,14}\Z",
    message="Le numéro de téléphone doit être au format international (ex. +2250701020304).",
)


class UserRole(models.TextChoices):
    CUSTOMER = "CUSTOMER", "Client"
    DEPOT_MANAGER = "DEPOT_MANAGER", "Responsable de dépôt"
    ADMIN = "ADMIN", "Administrateur"


class UserManager(BaseUserManager):
    def create_user(
        self,
        email: str,
        phone: str,
        full_name: str,
        password: str | None = None,
        **extra_fields,
    ) -> "User":
        if not email:
            raise ValueError("L'adresse e-mail est obligatoire.")
        if not phone:
            raise ValueError("Le numéro de téléphone est obligatoire.")
        if not full_name:
            raise ValueError("Le nom complet est obligatoire.")

        normalized_email = self.normalize_email(email).strip().lower()
        extra_fields.setdefault("role", UserRole.CUSTOMER)
        extra_fields.setdefault("is_active", True)

        user = self.model(
            email=normalized_email,
            phone=phone.strip(),
            full_name=full_name.strip(),
            **extra_fields,
        )
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        phone: str,
        full_name: str,
        password: str | None = None,
        **extra_fields,
    ) -> "User":
        extra_fields.setdefault("role", UserRole.ADMIN)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superutilisateur doit avoir is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superutilisateur doit avoir is_superuser=True.")

        return self.create_user(
            email=email,
            phone=phone,
            full_name=full_name,
            password=password,
            **extra_fields,
        )


class User(AbstractBaseUser, PermissionsMixin, TimeStampedUUIDModel):
    """Utilisateur de la plateforme avec téléphone obligatoire et rôle unique."""

    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(
        max_length=20,
        unique=True,
        validators=[phone_e164_validator],
        help_text="Numéro au format international E.164 (ex. +2250701020304).",
    )
    full_name = models.CharField(max_length=150)
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.CUSTOMER,
        db_index=True,
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["phone", "full_name"]

    class Meta:
        verbose_name = "Utilisateur"
        verbose_name_plural = "Utilisateurs"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs) -> None:
        if self.email:
            self.email = self.email.strip().lower()
        if self.phone:
            self.phone = self.phone.strip()
        if self.full_name:
            self.full_name = self.full_name.strip()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.full_name} ({self.email})"


class SuspensionReason(models.TextChoices):
    NO_SHOW_THRESHOLD = "NO_SHOW_THRESHOLD", "Seuil de retraits non effectués dépassé"
    MANUAL = "MANUAL", "Suspension manuelle"


class CustomerSuspension(TimeStampedUUIDModel):
    """Suspension temporaire de la capacité de commander pour un client (CDC §7.9)."""

    customer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="suspensions",
    )
    starts_at = models.DateTimeField(default=timezone.now)
    ends_at = models.DateTimeField(db_index=True)
    reason = models.CharField(
        max_length=32,
        choices=SuspensionReason.choices,
        default=SuspensionReason.NO_SHOW_THRESHOLD,
    )
    triggering_no_show_count = models.PositiveSmallIntegerField(default=0)
    lifted_at = models.DateTimeField(null=True, blank=True)
    lifted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lifted_suspensions",
    )
    lift_reason = models.TextField(blank=True, default="")

    class Meta:
        verbose_name = "Suspension client"
        verbose_name_plural = "Suspensions clients"
        ordering = ["-starts_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_at__gt=F("starts_at")),
                name="accounts_suspension_ends_after_starts",
            ),
        ]
        indexes = [
            models.Index(fields=["customer", "ends_at"]),
        ]

    @property
    def is_currently_active(self) -> bool:
        now = timezone.now()
        return self.lifted_at is None and self.starts_at <= now < self.ends_at

    def __str__(self) -> str:
        return f"Suspension {self.customer.email} jusqu'au {self.ends_at:%Y-%m-%d %H:%M}"
