"""Logique métier d'écriture du module accounts (inscription, JWT hybride, suspensions)."""

from dataclasses import dataclass

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import CustomerSuspension, User, UserRole
from apps.core.exceptions import (
    AuthenticationDomainError,
    ConflictDomainError,
    ValidationDomainError,
)
from apps.core.services import record_audit_log


@dataclass(frozen=True)
class AuthTokens:
    access_token: str
    refresh_token: str


def register_customer(
    *,
    email: str,
    phone: str,
    full_name: str,
    password: str,
) -> User:
    """Inscrit un nouveau compte client (rôle CUSTOMER forcé côté serveur)."""
    normalized_email = email.strip().lower()
    normalized_phone = phone.strip()

    if User.objects.filter(email__iexact=normalized_email).exists():
        raise ConflictDomainError(
            "Un compte existe déjà avec cette adresse e-mail.",
            code="EMAIL_ALREADY_EXISTS",
            details={"email": ["Cette adresse e-mail est déjà utilisée."]},
        )

    if User.objects.filter(phone=normalized_phone).exists():
        raise ConflictDomainError(
            "Un compte existe déjà avec ce numéro de téléphone.",
            code="PHONE_ALREADY_EXISTS",
            details={"phone": ["Ce numéro de téléphone est déjà utilisé."]},
        )

    candidate = User(
        email=normalized_email,
        phone=normalized_phone,
        full_name=full_name.strip(),
        role=UserRole.CUSTOMER,
    )
    try:
        candidate.full_clean(exclude=["password"])
    except DjangoValidationError as exc:
        raise ValidationDomainError(
            "Les informations d'inscription sont invalides.",
            details=exc.message_dict,
        ) from exc

    try:
        validate_password(password, user=candidate)
    except DjangoValidationError as exc:
        raise ValidationDomainError(
            "Le mot de passe ne respecte pas les exigences de sécurité.",
            details={"password": list(exc.messages)},
        ) from exc

    try:
        return User.objects.create_user(
            email=normalized_email,
            phone=normalized_phone,
            full_name=full_name.strip(),
            password=password,
            role=UserRole.CUSTOMER,
        )
    except DjangoValidationError as exc:
        raise ValidationDomainError(
            "Les informations d'inscription sont invalides.",
            details=exc.message_dict,
        ) from exc
    except IntegrityError as exc:
        raise ConflictDomainError(
            "Un compte avec cet e-mail ou ce téléphone existe déjà.",
            code="ACCOUNT_ALREADY_EXISTS",
        ) from exc


def authenticate_user(*, email: str, password: str) -> User:
    """Authentifie un utilisateur par e-mail et mot de passe."""
    normalized_email = email.strip().lower()
    user = authenticate(username=normalized_email, password=password)
    if user is None:
        raise AuthenticationDomainError(
            "Identifiants invalides.",
            code="INVALID_CREDENTIALS",
        )
    if not user.is_active:
        raise AuthenticationDomainError(
            "Ce compte est désactivé.",
            code="ACCOUNT_DISABLED",
        )
    return user


def issue_auth_tokens(*, user: User) -> AuthTokens:
    """Émet une paire Access/Refresh JWT pour l'utilisateur."""
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    return AuthTokens(
        access_token=str(refresh.access_token),
        refresh_token=str(refresh),
    )


def rotate_refresh_token(*, raw_refresh_token: str | None) -> AuthTokens:
    """Valide, révoque l'ancien refresh token et émet une nouvelle paire JWT."""
    if not raw_refresh_token:
        raise AuthenticationDomainError(
            "Jeton de renouvellement manquant.",
            code="REFRESH_TOKEN_MISSING",
        )

    try:
        old_refresh = RefreshToken(raw_refresh_token)
        user_id = old_refresh["user_id"]
    except (TokenError, KeyError) as exc:
        raise AuthenticationDomainError(
            "Jeton de renouvellement invalide ou expiré.",
            code="REFRESH_TOKEN_INVALID",
        ) from exc

    try:
        user = User.objects.get(pk=user_id, is_active=True)
    except User.DoesNotExist as exc:
        raise AuthenticationDomainError(
            "Compte introuvable ou désactivé.",
            code="ACCOUNT_DISABLED",
        ) from exc

    try:
        old_refresh.blacklist()
    except TokenError as exc:
        raise AuthenticationDomainError(
            "Jeton de renouvellement déjà révoqué.",
            code="REFRESH_TOKEN_INVALID",
        ) from exc

    return issue_auth_tokens(user=user)


def revoke_refresh_token(*, raw_refresh_token: str | None) -> None:
    """Révoque le refresh token lors de la déconnexion (idempotent)."""
    if not raw_refresh_token:
        return
    try:
        token = RefreshToken(raw_refresh_token)
        token.blacklist()
    except TokenError:
        return


def update_profile(
    *,
    user: User,
    full_name: str | None = None,
    phone: str | None = None,
) -> User:
    """Met à jour les informations autorisées du profil utilisateur."""
    update_fields: list[str] = ["updated_at"]

    if full_name is not None:
        user.full_name = full_name.strip()
        update_fields.append("full_name")

    if phone is not None:
        normalized_phone = phone.strip()
        if (
            normalized_phone != user.phone
            and User.objects.filter(phone=normalized_phone).exclude(pk=user.pk).exists()
        ):
            raise ConflictDomainError(
                "Ce numéro de téléphone est déjà associé à un autre compte.",
                code="PHONE_ALREADY_EXISTS",
                details={"phone": ["Ce numéro de téléphone est déjà utilisé."]},
            )
        user.phone = normalized_phone
        update_fields.append("phone")

    try:
        user.full_clean()
        user.save(update_fields=update_fields)
    except DjangoValidationError as exc:
        raise ValidationDomainError(
            "Les informations du profil sont invalides.",
            details=exc.message_dict,
        ) from exc

    return user


@transaction.atomic
def lift_suspension(
    *,
    suspension: CustomerSuspension,
    actor: User,
    reason: str,
) -> CustomerSuspension:
    """Lève de manière anticipée une suspension client et journalise l'action."""
    locked = CustomerSuspension.objects.select_for_update().get(pk=suspension.pk)
    if locked.lifted_at is not None:
        raise ConflictDomainError(
            "Cette suspension a déjà été levée.",
            code="SUSPENSION_ALREADY_LIFTED",
        )
    if not reason.strip():
        raise ValidationDomainError(
            "Un motif est obligatoire pour lever une suspension.",
            details={"reason": ["Ce champ est obligatoire."]},
        )

    before = {"lifted_at": None, "ends_at": locked.ends_at.isoformat()}
    locked.lifted_at = timezone.now()
    locked.lifted_by = actor
    locked.lift_reason = reason.strip()
    locked.save(update_fields=["lifted_at", "lifted_by", "lift_reason", "updated_at"])

    record_audit_log(
        actor=actor,
        action="CUSTOMER_SUSPENSION_LIFTED",
        resource_type="CustomerSuspension",
        resource_id=locked.pk,
        before_state=before,
        after_state={"lifted_at": locked.lifted_at.isoformat(), "lifted_by": str(actor.pk)},
        reason=locked.lift_reason,
    )
    return locked
