"""Services transactionnels du cycle de vie des commandes (machine à 6 états, CDC §7, §8)."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import CustomerSuspension, User, UserRole
from apps.catalog.models import Brand, Product, ProductStatus
from apps.core.exceptions import (
    ConflictDomainError,
    ForbiddenDomainError,
    NotFoundDomainError,
    ValidationDomainError,
)
from apps.core.models import PlatformSetting
from apps.depots.models import (
    Depot,
    DepotProductOffer,
    DepotStatus,
    OfferExchangeBrand,
    OfferOperation,
    OperationType,
)
from apps.depots.selectors import OpenStatus, compute_depot_open_state
from apps.inventory.services import (
    assert_depot_editable,
    commit_order_pickup,
    release_order_reservations,
    reserve_stock_for_order,
)
from apps.orders.models import (
    ACTIVE_ORDER_STATUSES,
    Order,
    OrderCancellationSource,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentMethod,
    PaymentRecord,
    PaymentStatus,
    generate_order_reference,
)

VALID_PAYMENT_METHODS = frozenset(PaymentMethod.values)
VALID_OPERATION_TYPES = frozenset(OperationType.values)


def _apply_expiration_to_locked_order(
    *,
    locked_order: Order,
    now: datetime,
    reason: str,
    counted_as_no_show: bool,
) -> Order:
    """Fait transiter une commande verrouillée vers EXPIRED et libère sa réservation."""
    previous_status = locked_order.status
    locked_order.status = OrderStatus.EXPIRED
    locked_order.expired_at = now
    locked_order.status_reason = reason
    locked_order.counted_as_no_show = counted_as_no_show
    locked_order.save(
        update_fields=[
            "status",
            "expired_at",
            "status_reason",
            "counted_as_no_show",
            "updated_at",
        ]
    )

    OrderStatusHistory.objects.create(
        order=locked_order,
        from_status=previous_status,
        to_status=OrderStatus.EXPIRED,
        actor=None,
        reason=reason,
    )
    release_order_reservations(order=locked_order, actor=None, reason=reason)
    return locked_order


def _is_order_past_deadline(order: Order, now: datetime) -> tuple[bool, bool, str]:
    """Retourne (is_expired, counted_as_no_show, reason) pour une commande active."""
    if order.status == OrderStatus.PENDING and now > order.response_deadline_at:
        return True, False, "Délai de réponse du dépôt dépassé."
    if (
        order.status == OrderStatus.CONFIRMED
        and order.pickup_deadline_at is not None
        and now > order.pickup_deadline_at
    ):
        return True, True, "Échéance de retrait dépassée sans retrait."
    return False, False, ""


def expire_order(*, order: Order, now: datetime | None = None) -> tuple[Order, bool]:
    """Expire de manière idempotente une commande active dont l'échéance est dépassée."""
    reference_now = now or timezone.now()
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        is_expired, is_no_show, reason = _is_order_past_deadline(locked, reference_now)
        if not is_expired:
            return locked, False
        _apply_expiration_to_locked_order(
            locked_order=locked,
            now=reference_now,
            reason=reason,
            counted_as_no_show=is_no_show,
        )
        return locked, True


def compute_pickup_deadline(
    *,
    depot: Depot,
    confirmed_at: datetime,
    settings_obj: PlatformSetting | None = None,
) -> datetime:
    """Calcule min(confirmed_at + délai retrait, heure de fermeture du jour dans le fuseau)."""
    cfg = settings_obj or PlatformSetting.load()
    tz = ZoneInfo(cfg.timezone)
    local_now = confirmed_at.astimezone(tz)
    closing_dt = datetime.combine(local_now.date(), depot.closing_time, tzinfo=tz)
    candidate = local_now + timedelta(minutes=cfg.order_pickup_timeout_minutes)
    return min(candidate, closing_dt)


def _resolve_empty_return_product(*, item: OrderItem) -> tuple[Product | None, int, str]:
    """Détermine le produit vide à créditer lors d'un retrait (recharge / échange)."""
    if item.operation_type == OperationType.REFILL:
        return (
            item.product,
            item.quantity,
            f"Retour bouteille vide (recharge) - commande {item.order.reference}",
        )
    if item.operation_type == OperationType.EXCHANGE and item.exchange_brand_id:
        matching_product = (
            Product.objects.filter(
                brand_id=item.exchange_brand_id,
                capacity_kg=item.product.capacity_kg,
                product_type=item.product.product_type,
            )
            .order_by("-status", "created_at")
            .first()
        )
        target = matching_product or item.product
        return (
            target,
            item.quantity,
            f"Retour bouteille vide échange ({item.exchange_brand_name_snapshot}) - "
            f"commande {item.order.reference}",
        )
    return None, 0, ""


def create_order(
    *,
    customer: User,
    depot: Depot,
    product: Product,
    operation_type: str,
    quantity: int,
    exchange_brand: Brand | None = None,
    now: datetime | None = None,
) -> Order:
    """Crée une commande EN_ATTENTE, fige les prix et réserve atomiquement le stock (CDC §6.3, §7.4)."""
    reference_now = now or timezone.now()

    if customer.role != UserRole.CUSTOMER:
        raise ForbiddenDomainError(
            "Seuls les comptes clients peuvent passer commande.",
            code="CUSTOMER_ROLE_REQUIRED",
        )

    if operation_type not in VALID_OPERATION_TYPES:
        raise ValidationDomainError(
            "Type d'opération invalide.",
            details={"operation_type": ["Opération non reconnue."]},
        )

    cfg = PlatformSetting.load()
    if (
        isinstance(quantity, bool)
        or not isinstance(quantity, int)
        or quantity < 1
        or quantity > cfg.max_quantity_per_order
    ):
        raise ValidationDomainError(
            f"La quantité doit être comprise entre 1 et {cfg.max_quantity_per_order}.",
            details={
                "quantity": [
                    f"Doit être un entier compris entre 1 et {cfg.max_quantity_per_order}."
                ]
            },
        )

    if operation_type == OperationType.EXCHANGE and exchange_brand is None:
        raise ValidationDomainError(
            "La marque de la bouteille vide est obligatoire pour un échange.",
            details={"exchange_brand_id": ["Ce champ est obligatoire pour un échange."]},
        )
    if operation_type != OperationType.EXCHANGE and exchange_brand is not None:
        raise ValidationDomainError(
            "La marque de bouteille vide ne s'applique qu'à l'opération Échange.",
            details={"exchange_brand_id": ["Champ non autorisé pour cette opération."]},
        )

    # Phase 1 : expirer à la volée toute commande active déjà échue du client (transaction dédiée)
    existing_active = (
        Order.objects.filter(customer=customer, status__in=ACTIVE_ORDER_STATUSES)
        .order_by("-created_at")
        .first()
    )
    if existing_active is not None:
        expire_order(order=existing_active, now=reference_now)

    # Phase 2 : transaction atomique verrouillant le client puis le stock
    with transaction.atomic():
        locked_customer = User.objects.select_for_update().get(pk=customer.pk)
        if not locked_customer.is_active:
            raise ForbiddenDomainError(
                "Ce compte est désactivé.",
                code="ACCOUNT_DISABLED",
            )

        active_suspension = (
            CustomerSuspension.objects.filter(
                customer=locked_customer,
                lifted_at__isnull=True,
                starts_at__lte=reference_now,
                ends_at__gt=reference_now,
            )
            .order_by("-ends_at")
            .first()
        )
        if active_suspension is not None:
            raise ForbiddenDomainError(
                "Votre compte est temporairement suspendu pour les commandes.",
                code="CUSTOMER_SUSPENDED",
                details={"ends_at": active_suspension.ends_at.isoformat()},
            )

        still_active = (
            Order.objects.filter(customer=locked_customer, status__in=ACTIVE_ORDER_STATUSES)
            .only("id")
            .first()
        )
        if still_active is not None:
            raise ConflictDomainError(
                "Vous avez déjà une commande active en cours.",
                code="ACTIVE_ORDER_EXISTS",
                details={"active_order_id": str(still_active.pk)},
            )

        fresh_depot = Depot.objects.filter(pk=depot.pk).first()
        if fresh_depot is None:
            raise NotFoundDomainError("Dépôt introuvable.", code="NOT_FOUND")
        if fresh_depot.status != DepotStatus.ACTIVE:
            raise ConflictDomainError(
                "Ce dépôt n'accepte pas de commandes actuellement.",
                code="DEPOT_UNAVAILABLE",
                details={"status": fresh_depot.status},
            )

        open_state = compute_depot_open_state(
            depot=fresh_depot,
            settings_obj=cfg,
            at=reference_now,
        )
        if open_state.open_status == OpenStatus.CLOSED:
            raise ConflictDomainError(
                "Votre commande n'a pas pu être enregistrée, car le dépôt est actuellement fermé. "
                "Consultez ses horaires d'ouverture pour passer une nouvelle commande.",
                code="DEPOT_CLOSED",
                details={"reopens_at": open_state.reopens_at.strftime("%H:%M")},
            )
        if not open_state.can_order:
            raise ConflictDomainError(
                f"Votre commande n'a pas pu être enregistrée, car le dépôt n'accepte plus de "
                f"commandes dans les {cfg.order_cutoff_before_close_minutes} minutes précédant "
                "sa fermeture.",
                code="ORDER_CUTOFF_REACHED",
                details={
                    "cutoff_minutes": cfg.order_cutoff_before_close_minutes,
                    "closing_time": fresh_depot.closing_time.strftime("%H:%M"),
                },
            )

        fresh_product = Product.objects.select_related("brand").filter(pk=product.pk).first()
        if (
            fresh_product is None
            or fresh_product.status != ProductStatus.PUBLISHED
            or not fresh_product.brand.is_active
        ):
            raise ValidationDomainError(
                "Ce produit n'est pas disponible à la commande.",
                details={"product_id": ["Produit non publié ou marque inactive."]},
            )

        offer = (
            DepotProductOffer.objects.filter(
                depot=fresh_depot,
                product=fresh_product,
                is_active=True,
            )
            .first()
        )
        if offer is None:
            raise ValidationDomainError(
                "Ce produit n'est pas commercialisé par ce dépôt.",
                details={"product_id": ["Aucune offre active pour ce produit dans ce dépôt."]},
            )

        operation = (
            OfferOperation.objects.filter(
                offer=offer,
                operation_type=operation_type,
                is_active=True,
            )
            .first()
        )
        if operation is None:
            raise ValidationDomainError(
                "Cette opération n'est pas proposée par ce dépôt pour ce produit.",
                details={"operation_type": ["Opération non disponible sur cette offre."]},
            )

        accepted_exchange_brand: Brand | None = None
        if operation_type == OperationType.EXCHANGE:
            assert exchange_brand is not None
            accepted = OfferExchangeBrand.objects.select_related("accepted_brand").filter(
                offer=offer,
                accepted_brand_id=exchange_brand.pk,
                accepted_brand__is_active=True,
            ).first()
            if accepted is None:
                raise ValidationDomainError(
                    "Cette marque de bouteille vide n'est pas acceptée en échange par ce dépôt.",
                    details={"exchange_brand_id": ["Marque non acceptée pour cet échange."]},
                )
            accepted_exchange_brand = accepted.accepted_brand

        unit_gas = operation.gas_price
        unit_bottle = operation.bottle_price
        unit_deposit = operation.deposit_amount
        unit_total = operation.total_unit_price
        line_total = unit_total * quantity
        response_deadline = reference_now + timedelta(minutes=cfg.order_response_timeout_minutes)

        order: Order | None = None
        for _ in range(5):
            try:
                with transaction.atomic():
                    order = Order.objects.create(
                        reference=generate_order_reference(),
                        customer=locked_customer,
                        depot=fresh_depot,
                        status=OrderStatus.PENDING,
                        payment_status=PaymentStatus.PENDING,
                        total_amount=line_total,
                        response_deadline_at=response_deadline,
                    )
                    break
            except IntegrityError as exc:
                msg = str(exc)
                if "orders_unique_active_order_per_customer" in msg:
                    raise ConflictDomainError(
                        "Vous avez déjà une commande active en cours.",
                        code="ACTIVE_ORDER_EXISTS",
                    ) from exc
                if "reference" not in msg:
                    raise

        if order is None:
            raise ConflictDomainError(
                "Impossible de générer une référence de commande unique.",
                code="ORDER_REFERENCE_CONFLICT",
            )

        OrderItem.objects.create(
            order=order,
            product=fresh_product,
            operation_type=operation_type,
            exchange_brand=accepted_exchange_brand,
            quantity=quantity,
            product_name_snapshot=fresh_product.name,
            brand_name_snapshot=fresh_product.brand.name,
            capacity_kg_snapshot=fresh_product.capacity_kg,
            exchange_brand_name_snapshot=(
                accepted_exchange_brand.name if accepted_exchange_brand else ""
            ),
            unit_gas_price=unit_gas,
            unit_bottle_price=unit_bottle,
            unit_deposit_amount=unit_deposit,
            unit_total_price=unit_total,
            line_total_amount=line_total,
        )

        OrderStatusHistory.objects.create(
            order=order,
            from_status="",
            to_status=OrderStatus.PENDING,
            actor=locked_customer,
            reason="Création de la commande client.",
        )

        # Réservation atomique (en cas d'INSUFFICIENT_STOCK, toute la transaction est annulée)
        reserve_stock_for_order(
            order=order,
            depot=fresh_depot,
            product=fresh_product,
            operation_type=operation_type,
            quantity=quantity,
            expires_at=response_deadline,
            actor=locked_customer,
        )

        return order


def accept_order(
    *,
    order: Order,
    actor: User,
    depot: Depot | None = None,
    now: datetime | None = None,
) -> Order:
    """Confirme une commande EN_ATTENTE (lazy check 15 min + calcul pickup_deadline_at borné)."""
    reference_now = now or timezone.now()
    expired_now = False

    with transaction.atomic():
        locked = Order.objects.select_for_update().select_related("depot").get(pk=order.pk)
        if depot is not None and locked.depot_id != depot.pk:
            raise NotFoundDomainError("Commande introuvable.", code="NOT_FOUND")
        assert_depot_editable(locked.depot)

        if locked.status == OrderStatus.PENDING:
            is_expired, is_no_show, reason = _is_order_past_deadline(locked, reference_now)
            if is_expired:
                _apply_expiration_to_locked_order(
                    locked_order=locked,
                    now=reference_now,
                    reason=reason,
                    counted_as_no_show=is_no_show,
                )
                expired_now = True
            else:
                cfg = PlatformSetting.load()
                pickup_deadline = compute_pickup_deadline(
                    depot=locked.depot,
                    confirmed_at=reference_now,
                    settings_obj=cfg,
                )
                if pickup_deadline <= reference_now:
                    raise ConflictDomainError(
                        "Le dépôt est déjà fermé : impossible de confirmer un retrait aujourd'hui.",
                        code="DEPOT_CLOSED",
                    )

                locked.status = OrderStatus.CONFIRMED
                locked.confirmed_at = reference_now
                locked.pickup_deadline_at = pickup_deadline
                locked.save(
                    update_fields=["status", "confirmed_at", "pickup_deadline_at", "updated_at"]
                )

                # Prolonge expires_at de la réservation active jusqu'à pickup_deadline_at
                locked.stock_reservations.filter(status="ACTIVE").update(
                    expires_at=pickup_deadline,
                    updated_at=reference_now,
                )

                OrderStatusHistory.objects.create(
                    order=locked,
                    from_status=OrderStatus.PENDING,
                    to_status=OrderStatus.CONFIRMED,
                    actor=actor,
                    reason="Commande acceptée par le dépôt.",
                )
                return locked
        else:
            raise ConflictDomainError(
                f"Impossible d'accepter une commande au statut {locked.status}.",
                code="INVALID_ORDER_TRANSITION",
                details={"current_status": locked.status, "target_status": OrderStatus.CONFIRMED},
            )

    if expired_now:
        raise ConflictDomainError(
            "Le délai de réponse du dépôt est dépassé. La commande a expiré.",
            code="ORDER_EXPIRED",
        )
    raise AssertionError("Unreachable")


def refuse_order(
    *,
    order: Order,
    actor: User,
    reason: str,
    depot: Depot | None = None,
    now: datetime | None = None,
) -> Order:
    """Refuse une commande EN_ATTENTE (motif obligatoire) et libère le stock."""
    if not reason or not reason.strip():
        raise ValidationDomainError(
            "Un motif est obligatoire pour refuser une commande.",
            details={"reason": ["Ce champ est obligatoire."]},
        )

    reference_now = now or timezone.now()
    clean_reason = reason.strip()
    expired_now = False

    with transaction.atomic():
        locked = Order.objects.select_for_update().select_related("depot").get(pk=order.pk)
        if depot is not None and locked.depot_id != depot.pk:
            raise NotFoundDomainError("Commande introuvable.", code="NOT_FOUND")
        assert_depot_editable(locked.depot)

        if locked.status == OrderStatus.PENDING:
            is_expired, is_no_show, exp_reason = _is_order_past_deadline(locked, reference_now)
            if is_expired:
                _apply_expiration_to_locked_order(
                    locked_order=locked,
                    now=reference_now,
                    reason=exp_reason,
                    counted_as_no_show=is_no_show,
                )
                expired_now = True
            else:
                locked.status = OrderStatus.REFUSED
                locked.refused_at = reference_now
                locked.status_reason = clean_reason
                locked.save(update_fields=["status", "refused_at", "status_reason", "updated_at"])

                OrderStatusHistory.objects.create(
                    order=locked,
                    from_status=OrderStatus.PENDING,
                    to_status=OrderStatus.REFUSED,
                    actor=actor,
                    reason=clean_reason,
                )
                release_order_reservations(
                    order=locked,
                    actor=actor,
                    reason=f"Refus commande {locked.reference} : {clean_reason}",
                )
                return locked
        else:
            raise ConflictDomainError(
                f"Impossible de refuser une commande au statut {locked.status}.",
                code="INVALID_ORDER_TRANSITION",
                details={"current_status": locked.status, "target_status": OrderStatus.REFUSED},
            )

    if expired_now:
        raise ConflictDomainError(
            "Le délai de réponse du dépôt est dépassé. La commande a expiré.",
            code="ORDER_EXPIRED",
        )
    raise AssertionError("Unreachable")


def cancel_order_by_customer(
    *,
    order: Order,
    customer: User,
    reason: str = "",
    now: datetime | None = None,
) -> Order:
    """Annule une commande EN_ATTENTE ou CONFIRMEE par son client (non comptée en no-show)."""
    reference_now = now or timezone.now()
    clean_reason = reason.strip() if reason else ""
    expired_now = False

    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.customer_id != customer.pk:
            raise NotFoundDomainError("Commande introuvable.", code="NOT_FOUND")

        if locked.status in ACTIVE_ORDER_STATUSES:
            is_expired, is_no_show, exp_reason = _is_order_past_deadline(locked, reference_now)
            if is_expired:
                _apply_expiration_to_locked_order(
                    locked_order=locked,
                    now=reference_now,
                    reason=exp_reason,
                    counted_as_no_show=is_no_show,
                )
                expired_now = True
            else:
                previous_status = locked.status
                locked.status = OrderStatus.CANCELLED
                locked.cancelled_at = reference_now
                locked.status_reason = clean_reason
                locked.cancellation_source = OrderCancellationSource.CUSTOMER
                locked.counted_as_no_show = False
                locked.save(
                    update_fields=[
                        "status",
                        "cancelled_at",
                        "status_reason",
                        "cancellation_source",
                        "counted_as_no_show",
                        "updated_at",
                    ]
                )

                OrderStatusHistory.objects.create(
                    order=locked,
                    from_status=previous_status,
                    to_status=OrderStatus.CANCELLED,
                    actor=customer,
                    reason=clean_reason or "Annulation par le client.",
                )
                release_order_reservations(
                    order=locked,
                    actor=customer,
                    reason=clean_reason or f"Annulation client commande {locked.reference}",
                )
                return locked
        else:
            raise ConflictDomainError(
                f"Impossible d'annuler une commande au statut {locked.status}.",
                code="INVALID_ORDER_TRANSITION",
                details={"current_status": locked.status, "target_status": OrderStatus.CANCELLED},
            )

    if expired_now:
        raise ConflictDomainError(
            "L'échéance de la commande est dépassée. La commande a expiré.",
            code="ORDER_EXPIRED",
        )
    raise AssertionError("Unreachable")


def cancel_order_non_conformity(
    *,
    order: Order,
    actor: User,
    reason: str,
    depot: Depot | None = None,
    now: datetime | None = None,
) -> Order:
    """Annule une commande CONFIRMEE pour bouteille vide non conforme au comptoir (motif requis)."""
    if not reason or not reason.strip():
        raise ValidationDomainError(
            "Un motif est obligatoire pour annuler une commande pour non-conformité.",
            details={"reason": ["Ce champ est obligatoire."]},
        )

    reference_now = now or timezone.now()
    clean_reason = reason.strip()
    expired_now = False

    with transaction.atomic():
        locked = Order.objects.select_for_update().select_related("depot").get(pk=order.pk)
        if depot is not None and locked.depot_id != depot.pk:
            raise NotFoundDomainError("Commande introuvable.", code="NOT_FOUND")
        assert_depot_editable(locked.depot)

        if locked.status == OrderStatus.CONFIRMED:
            is_expired, is_no_show, exp_reason = _is_order_past_deadline(locked, reference_now)
            if is_expired:
                _apply_expiration_to_locked_order(
                    locked_order=locked,
                    now=reference_now,
                    reason=exp_reason,
                    counted_as_no_show=is_no_show,
                )
                expired_now = True
            else:
                locked.status = OrderStatus.CANCELLED
                locked.cancelled_at = reference_now
                locked.status_reason = clean_reason
                locked.cancellation_source = OrderCancellationSource.DEPOT_NON_CONFORMITY
                locked.counted_as_no_show = False
                locked.save(
                    update_fields=[
                        "status",
                        "cancelled_at",
                        "status_reason",
                        "cancellation_source",
                        "counted_as_no_show",
                        "updated_at",
                    ]
                )

                OrderStatusHistory.objects.create(
                    order=locked,
                    from_status=OrderStatus.CONFIRMED,
                    to_status=OrderStatus.CANCELLED,
                    actor=actor,
                    reason=clean_reason,
                )
                release_order_reservations(
                    order=locked,
                    actor=actor,
                    reason=f"Non-conformité bouteille vide ({locked.reference}) : {clean_reason}",
                )
                return locked
        else:
            raise ConflictDomainError(
                f"Seule une commande confirmée peut être annulée pour non-conformité "
                f"(statut actuel : {locked.status}).",
                code="INVALID_ORDER_TRANSITION",
                details={"current_status": locked.status, "target_status": OrderStatus.CANCELLED},
            )

    if expired_now:
        raise ConflictDomainError(
            "L'échéance de retrait est dépassée. La commande a expiré.",
            code="ORDER_EXPIRED",
        )
    raise AssertionError("Unreachable")


def complete_pickup(
    *,
    order: Order,
    actor: User,
    payment_method: str,
    received_amount: int | None = None,
    external_reference: str = "",
    notes: str = "",
    depot: Depot | None = None,
    now: datetime | None = None,
) -> Order:
    """Valide le retrait au comptoir : paiement, décrémentation physique et retour bouteille vide."""
    if payment_method not in VALID_PAYMENT_METHODS:
        raise ValidationDomainError(
            "Moyen de paiement invalide.",
            details={"payment_method": ["Utilisez CASH ou MOBILE_MONEY."]},
        )

    if received_amount is not None and (
        isinstance(received_amount, bool) or not isinstance(received_amount, int)
    ):
        raise ValidationDomainError(
            "Le montant reçu doit être un entier.",
            details={"received_amount": ["Entier requis."]},
        )

    reference_now = now or timezone.now()
    expired_now = False

    with transaction.atomic():
        locked = (
            Order.objects.select_for_update()
            .select_related("depot")
            .prefetch_related("items", "items__product", "items__exchange_brand")
            .get(pk=order.pk)
        )
        if depot is not None and locked.depot_id != depot.pk:
            raise NotFoundDomainError("Commande introuvable.", code="NOT_FOUND")
        assert_depot_editable(locked.depot)

        if locked.status == OrderStatus.CONFIRMED:
            is_expired, is_no_show, exp_reason = _is_order_past_deadline(locked, reference_now)
            if is_expired:
                _apply_expiration_to_locked_order(
                    locked_order=locked,
                    now=reference_now,
                    reason=exp_reason,
                    counted_as_no_show=is_no_show,
                )
                expired_now = True
            else:
                effective_received = (
                    locked.total_amount if received_amount is None else received_amount
                )
                if effective_received != locked.total_amount:
                    raise ValidationDomainError(
                        "Le montant reçu doit correspondre au montant total attendu.",
                        details={
                            "received_amount": [
                                f"Montant attendu : {locked.total_amount} FCFA."
                            ]
                        },
                    )

                item = locked.items.first()
                empty_product: Product | None = None
                empty_qty = 0
                empty_reason = ""
                if item is not None:
                    empty_product, empty_qty, empty_reason = _resolve_empty_return_product(
                        item=item
                    )

                commit_order_pickup(
                    order=locked,
                    actor=actor,
                    empty_return_product=empty_product,
                    empty_return_quantity=empty_qty,
                    empty_return_reason=empty_reason,
                )

                PaymentRecord.objects.create(
                    order=locked,
                    expected_amount=locked.total_amount,
                    received_amount=effective_received,
                    payment_method=payment_method,
                    status=PaymentStatus.PAID,
                    external_reference=(external_reference or "").strip(),
                    notes=(notes or "").strip(),
                    recorded_by=actor,
                    paid_at=reference_now,
                )

                locked.status = OrderStatus.PICKED_UP
                locked.payment_status = PaymentStatus.PAID
                locked.picked_up_at = reference_now
                locked.save(
                    update_fields=["status", "payment_status", "picked_up_at", "updated_at"]
                )

                OrderStatusHistory.objects.create(
                    order=locked,
                    from_status=OrderStatus.CONFIRMED,
                    to_status=OrderStatus.PICKED_UP,
                    actor=actor,
                    reason=f"Retrait validé ({payment_method}).",
                )
                return locked
        else:
            raise ConflictDomainError(
                f"Impossible d'enregistrer le retrait pour une commande au statut {locked.status}.",
                code="INVALID_ORDER_TRANSITION",
                details={"current_status": locked.status, "target_status": OrderStatus.PICKED_UP},
            )

    if expired_now:
        raise ConflictDomainError(
            "L'échéance de retrait est dépassée. La commande a expiré.",
            code="ORDER_EXPIRED",
        )
    raise AssertionError("Unreachable")
