"""Jalon 3 / Lot 2 — contrats des services métier ``apps.orders.services``.

Toutes les dates sont passées explicitement (``now=...``) en ``Africa/Douala`` :
aucun test ne dépend de l'horloge système. Chronologie de référence :
création 10:00 -> échéance de réponse 10:15 ; acceptation 10:05 -> retrait limite 12:05.
"""
import re
from datetime import timedelta
from decimal import Decimal

import pytest

from apps.core.exceptions import (
    ConflictDomainError,
    ForbiddenDomainError,
    NotFoundDomainError,
    ValidationDomainError,
)
from apps.depots.models import DepotStatus, OfferExchangeBrand, OfferOperation, OperationType
from apps.inventory.models import (
    DepotStock,
    StockCategory,
    StockMovementType,
    StockReservation,
    StockReservationStatus,
)
from apps.orders import services as order_services
from apps.orders.models import (
    Order,
    OrderCancellationSource,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentRecord,
    PaymentStatus,
)
from tests.domain_asserts import assert_domain_error
from tests.factories_catalog import make_brand, make_product
from tests.factories_inventory import make_stock
from tests.factories_orders import (
    BASE_NOW,
    NON_PUBLISHED_STATUS,
    at,
    available,
    history_of,
    make_order_in_state,
    make_order_setup,
    make_suspension,
    movements,
    place_order,
    stock_of,
)

pytestmark = pytest.mark.django_db

MIN = timedelta(minutes=1)


@pytest.fixture(autouse=True)
def _platform(platform_setting):
    """max_quantity_per_order=3 et order_cutoff_before_close_minutes=30 (valeurs du contrat)."""
    return platform_setting


@pytest.fixture
def setup():
    return make_order_setup()


def reload(order):
    return Order.objects.get(pk=order.pk)


def assert_nothing_created():
    assert Order.objects.count() == 0
    assert OrderItem.objects.count() == 0
    assert StockReservation.objects.count() == 0
    assert movements(StockMovementType.RESERVATION).count() == 0


# =========================================================================== #
# 1. create_order
# =========================================================================== #
class TestCreateOrderNominal:
    @pytest.mark.parametrize("quantity", [1, 2, 3])
    def test_refill(self, setup, customer, quantity):
        order = place_order(setup, customer, quantity=quantity)

        assert order.status == OrderStatus.PENDING
        assert order.payment_status == PaymentStatus.PENDING
        assert order.customer == customer
        assert order.depot == setup.depot
        assert re.fullmatch(r"FAY-[A-Z0-9]{6}", order.reference)
        assert order.response_deadline_at == BASE_NOW + timedelta(minutes=15)
        assert order.total_amount == Decimal("1000") * quantity
        assert order.pickup_deadline_at is None
        assert order.counted_as_no_show is False

        item = OrderItem.objects.get(order=order)
        assert item.operation_type == OperationType.REFILL
        assert item.quantity == quantity
        assert item.unit_gas_price == Decimal("1000")
        assert item.unit_bottle_price == 0 and item.unit_deposit_amount == 0
        assert item.unit_total_price == Decimal("1000")
        assert item.line_total_amount == Decimal("1000") * quantity
        assert item.exchange_brand_id is None

        stock = stock_of(setup.depot, setup.product)
        assert stock.physical_quantity == 10
        assert stock.reserved_quantity == quantity

        reservation = StockReservation.objects.get(order=order)
        assert reservation.status == StockReservationStatus.ACTIVE
        assert reservation.quantity == quantity
        assert reservation.stock_id == stock.pk

        movement = movements(StockMovementType.RESERVATION).get()
        assert movement.delta == -quantity

        assert [(h.from_status, h.to_status) for h in history_of(order)] == [
            ("", OrderStatus.PENDING)
        ]

    def test_exchange(self, setup, customer):
        order = place_order(setup, customer, operation_type=OperationType.EXCHANGE, quantity=2)
        item = OrderItem.objects.get(order=order)
        assert item.operation_type == OperationType.EXCHANGE
        assert item.exchange_brand_id == setup.exchange_brand.pk
        assert item.unit_total_price == Decimal("1500")
        assert order.total_amount == Decimal("3000")
        assert stock_of(setup.depot, setup.product).reserved_quantity == 2

    def test_first_acquisition_prices_include_bottle_and_deposit(self, setup, customer):
        order = place_order(
            setup, customer, operation_type=OperationType.FIRST_ACQUISITION, quantity=2
        )
        item = OrderItem.objects.get(order=order)
        assert item.unit_gas_price == Decimal("1000")
        assert item.unit_bottle_price == Decimal("5000")
        assert item.unit_deposit_amount == Decimal("2000")
        assert item.unit_total_price == Decimal("8000")
        assert item.line_total_amount == Decimal("16000")
        assert order.total_amount == Decimal("16000")

    def test_opening_time_is_inclusive(self, setup, customer):
        order = place_order(setup, customer, now=at(8, 0))
        assert order.status == OrderStatus.PENDING

    def test_two_customers_accumulate_reservations(self, setup, customer, other_customer):
        place_order(setup, customer, quantity=2)
        place_order(setup, other_customer, quantity=3)
        assert stock_of(setup.depot, setup.product).reserved_quantity == 5

    def test_price_freeze_after_catalog_change(self, setup, customer):
        order = place_order(setup, customer, quantity=2)
        OfferOperation.objects.filter(pk=setup.operations[OperationType.REFILL].pk).update(
            gas_price=Decimal("9999")
        )
        order = reload(order)
        item = OrderItem.objects.get(order=order)
        assert order.total_amount == Decimal("2000")
        assert item.unit_gas_price == Decimal("1000")
        assert item.unit_total_price == Decimal("1000")
        assert item.line_total_amount == Decimal("2000")


class TestCreateOrderCustomerRules:
    @pytest.mark.parametrize("fixture_name", ["depot_manager", "admin_user"])
    def test_non_customer_role_forbidden(self, request, setup, fixture_name):
        user = request.getfixturevalue(fixture_name)
        with pytest.raises(ForbiddenDomainError) as exc:
            place_order(setup, user)
        assert_domain_error(exc, ForbiddenDomainError, "CUSTOMER_ROLE_REQUIRED")
        assert_nothing_created()

    def test_suspended_customer_forbidden(self, setup, customer):
        make_suspension(
            customer,
            starts_at=BASE_NOW - timedelta(days=1),
            ends_at=BASE_NOW + timedelta(days=2),
        )
        with pytest.raises(ForbiddenDomainError) as exc:
            place_order(setup, customer)
        assert_domain_error(exc, ForbiddenDomainError, "CUSTOMER_SUSPENDED")
        assert "ends_at" in exc.value.details
        assert_nothing_created()

    def test_expired_suspension_is_ignored(self, setup, customer):
        make_suspension(
            customer,
            starts_at=BASE_NOW - timedelta(days=3),
            ends_at=BASE_NOW - timedelta(hours=1),
        )
        assert place_order(setup, customer).status == OrderStatus.PENDING

    def test_lifted_suspension_is_ignored(self, setup, customer):
        make_suspension(
            customer,
            starts_at=BASE_NOW - timedelta(days=1),
            ends_at=BASE_NOW + timedelta(days=2),
            lifted_at=BASE_NOW - timedelta(hours=1),
        )
        assert place_order(setup, customer).status == OrderStatus.PENDING

    @pytest.mark.parametrize("state", [OrderStatus.PENDING, OrderStatus.CONFIRMED])
    def test_active_order_blocks_a_new_one(self, setup, customer, state):
        make_order_in_state(setup, customer, state)
        with pytest.raises(ConflictDomainError) as exc:
            place_order(setup, customer, now=at(10, 10))
        assert_domain_error(exc, ConflictDomainError, "ACTIVE_ORDER_EXISTS")
        assert Order.objects.filter(customer=customer).count() == 1
        assert stock_of(setup.depot, setup.product).reserved_quantity == 1

    @pytest.mark.parametrize("state", [OrderStatus.CANCELLED, OrderStatus.REFUSED, OrderStatus.PICKED_UP, OrderStatus.EXPIRED])
    def test_final_order_does_not_block(self, setup, customer, state):
        make_order_in_state(setup, customer, state)
        new = place_order(setup, customer, now=at(11, 0))
        assert new.status == OrderStatus.PENDING

    def test_overdue_pending_order_is_expired_on_the_fly(self, setup, customer):
        old = place_order(setup, customer, quantity=3)  # échéance 10:15
        new = place_order(setup, customer, quantity=1, now=at(10, 16))
        assert new.status == OrderStatus.PENDING
        old = reload(old)
        assert old.status == OrderStatus.EXPIRED
        assert old.counted_as_no_show is False
        assert StockReservation.objects.get(order=old).status == StockReservationStatus.RELEASED
        assert stock_of(setup.depot, setup.product).reserved_quantity == 1

    def test_overdue_confirmed_order_is_expired_as_no_show_on_the_fly(self, setup, customer):
        old = make_order_in_state(setup, customer, OrderStatus.CONFIRMED, quantity=2)  # retrait 12:05
        new = place_order(setup, customer, quantity=1, now=at(12, 6))
        assert new.status == OrderStatus.PENDING
        old = reload(old)
        assert old.status == OrderStatus.EXPIRED
        assert old.counted_as_no_show is True
        assert stock_of(setup.depot, setup.product).reserved_quantity == 1


class TestCreateOrderDepotRules:
    @pytest.mark.parametrize(
        "status", [DepotStatus.PENDING, DepotStatus.SUSPENDED, DepotStatus.DISABLED]
    )
    def test_depot_not_active(self, customer, status):
        setup = make_order_setup(depot_status=status)
        with pytest.raises(ConflictDomainError) as exc:
            place_order(setup, customer)
        assert_domain_error(exc, ConflictDomainError, "DEPOT_UNAVAILABLE")
        assert_nothing_created()

    @pytest.mark.parametrize(
        "now", [at(6, 0), at(7, 59), at(20, 0), at(21, 0)], ids=["06h00", "07h59", "20h00", "21h00"]
    )
    def test_depot_closed(self, setup, customer, now):
        with pytest.raises(ConflictDomainError) as exc:
            place_order(setup, customer, now=now)
        assert_domain_error(exc, ConflictDomainError, "DEPOT_CLOSED")
        assert_nothing_created()

    @pytest.mark.parametrize("now", [at(19, 31), at(19, 45), at(19, 59)])
    def test_cutoff_before_closing(self, setup, customer, now):
        with pytest.raises(ConflictDomainError) as exc:
            place_order(setup, customer, now=now)
        assert_domain_error(exc, ConflictDomainError, "ORDER_CUTOFF_REACHED")
        assert_nothing_created()

    def test_just_before_cutoff_is_accepted(self, setup, customer):
        assert place_order(setup, customer, now=at(19, 29)).status == OrderStatus.PENDING

    def test_cutoff_follows_platform_setting(self, setup, customer, platform_setting):
        platform_setting.order_cutoff_before_close_minutes = 60
        platform_setting.save()
        with pytest.raises(ConflictDomainError) as exc:
            place_order(setup, customer, now=at(19, 15))
        assert_domain_error(exc, ConflictDomainError, "ORDER_CUTOFF_REACHED")


class TestCreateOrderValidation:
    @pytest.mark.parametrize("quantity", [0, -1, 4, 100, True, False])
    def test_invalid_quantity(self, setup, customer, quantity):
        with pytest.raises(ValidationDomainError):
            place_order(setup, customer, quantity=quantity)
        assert_nothing_created()

    def test_max_quantity_follows_platform_setting(self, setup, customer, platform_setting):
        platform_setting.max_quantity_per_order = 2
        platform_setting.save()
        with pytest.raises(ValidationDomainError):
            place_order(setup, customer, quantity=3)
        assert place_order(setup, customer, quantity=2).status == OrderStatus.PENDING

    def test_inactive_offer(self, setup, customer):
        setup.offer.is_active = False
        setup.offer.save(update_fields=["is_active"])
        with pytest.raises(ValidationDomainError):
            place_order(setup, customer)
        assert_nothing_created()

    def test_product_without_offer_in_depot(self, setup, customer):
        with pytest.raises(ValidationDomainError):
            order_services.create_order(
                customer=customer,
                depot=setup.depot,
                product=make_product(),
                operation_type=OperationType.REFILL,
                quantity=1,
                now=BASE_NOW,
            )
        assert_nothing_created()

    def test_product_not_published(self, setup, customer):
        setup.product.status = NON_PUBLISHED_STATUS
        setup.product.save(update_fields=["status"])
        with pytest.raises(ValidationDomainError):
            place_order(setup, customer)
        assert_nothing_created()

    def test_inactive_brand(self, setup, customer):
        brand = setup.product.brand
        brand.is_active = False
        brand.save(update_fields=["is_active"])
        with pytest.raises(ValidationDomainError):
            place_order(setup, customer)
        assert_nothing_created()

    def test_inactive_operation(self, setup, customer):
        OfferOperation.objects.filter(pk=setup.operations[OperationType.REFILL].pk).update(
            is_active=False
        )
        with pytest.raises(ValidationDomainError):
            place_order(setup, customer)
        assert_nothing_created()

    def test_operation_not_offered(self, customer):
        setup = make_order_setup(operations=(OperationType.EXCHANGE,))
        with pytest.raises(ValidationDomainError):
            place_order(setup, customer, operation_type=OperationType.REFILL)
        assert_nothing_created()


class TestCreateOrderExchangeBrand:
    def test_exchange_requires_brand(self, setup, customer):
        with pytest.raises(ValidationDomainError):
            place_order(setup, customer, operation_type=OperationType.EXCHANGE, exchange_brand=None)
        assert_nothing_created()

    def test_exchange_brand_not_accepted_by_offer(self, setup, customer):
        with pytest.raises(ValidationDomainError):
            place_order(
                setup, customer, operation_type=OperationType.EXCHANGE, exchange_brand=make_brand()
            )
        assert_nothing_created()

    def test_exchange_brand_link_inactive(self, setup, customer):
        OfferExchangeBrand.objects.filter(pk=setup.exchange_link.pk).delete()
        with pytest.raises(ValidationDomainError):
            place_order(setup, customer, operation_type=OperationType.EXCHANGE)
        assert_nothing_created()

    @pytest.mark.parametrize("operation_type", [OperationType.REFILL, OperationType.FIRST_ACQUISITION])
    def test_exchange_brand_forbidden_for_other_operations(self, setup, customer, operation_type):
        with pytest.raises(ValidationDomainError):
            place_order(
                setup, customer, operation_type=operation_type, exchange_brand=setup.exchange_brand
            )
        assert_nothing_created()


class TestCreateOrderStock:
    def test_insufficient_stock_rolls_everything_back(self, customer):
        setup = make_order_setup(physical=1)
        with pytest.raises(ConflictDomainError) as exc:
            place_order(setup, customer, quantity=2)
        assert_domain_error(exc, ConflictDomainError, "INSUFFICIENT_STOCK")
        assert_nothing_created()
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (1, 0)
        # Le client n'est pas bloqué par l'échec.
        assert place_order(setup, customer, quantity=1).status == OrderStatus.PENDING

    def test_reserved_quantity_is_not_available(self, customer, other_customer):
        setup = make_order_setup(physical=3, reserved=2)
        with pytest.raises(ConflictDomainError) as exc:
            place_order(setup, customer, quantity=2)
        assert_domain_error(exc, ConflictDomainError, "INSUFFICIENT_STOCK")
        assert place_order(setup, other_customer, quantity=1).status == OrderStatus.PENDING
        assert available(stock_of(setup.depot, setup.product)) == 0

    def test_exact_available_stock_is_enough(self, customer):
        setup = make_order_setup(physical=2)
        place_order(setup, customer, quantity=2)
        assert available(stock_of(setup.depot, setup.product)) == 0

    @pytest.mark.parametrize("operation_type", [OperationType.REFILL, OperationType.EXCHANGE])
    def test_refill_and_exchange_only_reserve_full_stock(self, customer, operation_type):
        setup = make_order_setup(physical=0, new_physical=10)
        make_stock(
            depot=setup.depot,
            product=setup.product,
            category=StockCategory.EMPTY,
            physical_quantity=10,
        )
        with pytest.raises(ConflictDomainError) as exc:
            place_order(setup, customer, operation_type=operation_type)
        assert_domain_error(exc, ConflictDomainError, "INSUFFICIENT_STOCK")
        assert_nothing_created()

    def test_first_acquisition_prefers_new_stock(self, customer):
        setup = make_order_setup(new_physical=5)
        order = place_order(setup, customer, operation_type=OperationType.FIRST_ACQUISITION, quantity=2)
        reservation = StockReservation.objects.get(order=order)
        assert reservation.stock_id == setup.new_stock.pk
        assert stock_of(setup.depot, setup.product, StockCategory.NEW).reserved_quantity == 2
        assert stock_of(setup.depot, setup.product, StockCategory.FULL).reserved_quantity == 0

    def test_first_acquisition_uses_new_when_exactly_enough(self, customer):
        setup = make_order_setup(new_physical=2)
        order = place_order(setup, customer, operation_type=OperationType.FIRST_ACQUISITION, quantity=2)
        assert StockReservation.objects.get(order=order).stock_id == setup.new_stock.pk

    def test_first_acquisition_falls_back_to_full_when_new_is_short(self, customer):
        setup = make_order_setup(new_physical=1)
        order = place_order(setup, customer, operation_type=OperationType.FIRST_ACQUISITION, quantity=2)
        assert StockReservation.objects.get(order=order).stock_id == setup.stock.pk
        assert stock_of(setup.depot, setup.product, StockCategory.NEW).reserved_quantity == 0

    def test_first_acquisition_without_new_stock_uses_full(self, setup, customer):
        order = place_order(setup, customer, operation_type=OperationType.FIRST_ACQUISITION)
        assert StockReservation.objects.get(order=order).stock_id == setup.stock.pk

    def test_first_acquisition_insufficient_everywhere(self, customer):
        setup = make_order_setup(physical=1, new_physical=1)
        with pytest.raises(ConflictDomainError) as exc:
            place_order(setup, customer, operation_type=OperationType.FIRST_ACQUISITION, quantity=2)
        assert_domain_error(exc, ConflictDomainError, "INSUFFICIENT_STOCK")
        assert_nothing_created()


# =========================================================================== #
# Matrice transverse des transitions (accept / refuse / cancel / pickup)
# =========================================================================== #
ALLOWED_FROM = {
    "accept": {OrderStatus.PENDING},
    "refuse": {OrderStatus.PENDING},
    "cancel_customer": {OrderStatus.PENDING, OrderStatus.CONFIRMED},
    "cancel_non_conformity": {OrderStatus.CONFIRMED},
    "pickup": {OrderStatus.CONFIRMED},
}
VALID_CASES = [(n, s) for n, allowed in ALLOWED_FROM.items() for s in sorted(allowed)]
INVALID_CASES = [
    (n, s) for n, allowed in ALLOWED_FROM.items() for s in OrderStatus if s not in allowed
]
# Dernier instant valide : réponse 10:15 (PENDING) / retrait 12:05 (CONFIRMED, accepté à 10:05).
LAST_VALID_NOW = {OrderStatus.PENDING: at(10, 15), OrderStatus.CONFIRMED: at(12, 5)}


def invoke(name, setup, customer, order, now, *, actor=None, depot=None, by_customer=None):
    actor = actor or setup.manager
    if name == "accept":
        return order_services.accept_order(order=order, actor=actor, depot=depot, now=now)
    if name == "refuse":
        return order_services.refuse_order(
            order=order, actor=actor, reason="Rupture de stock", depot=depot, now=now
        )
    if name == "cancel_customer":
        return order_services.cancel_order_by_customer(
            order=order, customer=by_customer or customer, now=now
        )
    if name == "cancel_non_conformity":
        return order_services.cancel_order_non_conformity(
            order=order, actor=actor, reason="Bouteille non conforme", depot=depot, now=now
        )
    if name == "pickup":
        return order_services.complete_pickup(
            order=order, actor=actor, payment_method=PaymentMethod.CASH, depot=depot, now=now
        )
    raise AssertionError(name)


class TestTransitionMatrix:
    @pytest.mark.parametrize(("name", "state"), INVALID_CASES)
    def test_invalid_transition(self, setup, customer, name, state):
        order = make_order_in_state(setup, customer, state, quantity=2)
        stock_before = stock_of(setup.depot, setup.product)
        snapshot = (stock_before.physical_quantity, stock_before.reserved_quantity)

        with pytest.raises(ConflictDomainError) as exc:
            invoke(name, setup, customer, order, at(10, 10))

        assert_domain_error(exc, ConflictDomainError, "INVALID_ORDER_TRANSITION")
        assert reload(order).status == state
        stock_after = stock_of(setup.depot, setup.product)
        assert (stock_after.physical_quantity, stock_after.reserved_quantity) == snapshot

    @pytest.mark.parametrize(("name", "state"), VALID_CASES)
    def test_lazy_expiration_is_persisted(self, setup, customer, name, state):
        order = make_order_in_state(setup, customer, state, quantity=2)
        now = LAST_VALID_NOW[state] + MIN

        with pytest.raises(ConflictDomainError) as exc:
            invoke(name, setup, customer, order, now)

        assert_domain_error(exc, ConflictDomainError, "ORDER_EXPIRED")
        order = reload(order)  # l'expiration doit survivre à l'exception
        assert order.status == OrderStatus.EXPIRED
        assert order.counted_as_no_show is (state == OrderStatus.CONFIRMED)
        assert order.expired_at is not None
        reservation = StockReservation.objects.get(order=order)
        assert reservation.status == StockReservationStatus.RELEASED
        assert reservation.released_at is not None
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (10, 0)
        release = movements(StockMovementType.RELEASE).get()
        assert release.delta == 2
        assert not PaymentRecord.objects.filter(order=order).exists()
        assert history_of(order)[-1].to_status == OrderStatus.EXPIRED

    @pytest.mark.parametrize(("name", "state"), VALID_CASES)
    def test_deadline_instant_is_still_valid(self, setup, customer, name, state):
        order = make_order_in_state(setup, customer, state)
        result = invoke(name, setup, customer, order, LAST_VALID_NOW[state])
        assert result.status != OrderStatus.EXPIRED

    @pytest.mark.parametrize(
        "name,state",
        [
            ("accept", OrderStatus.PENDING),
            ("refuse", OrderStatus.PENDING),
            ("cancel_non_conformity", OrderStatus.CONFIRMED),
            ("pickup", OrderStatus.CONFIRMED),
        ],
    )
    def test_foreign_depot_is_not_found(self, setup, customer, name, state):
        order = make_order_in_state(setup, customer, state)
        other = make_order_setup()
        with pytest.raises(NotFoundDomainError):
            invoke(name, setup, customer, order, at(10, 10), actor=other.manager, depot=other.depot)
        assert reload(order).status == state

    def test_foreign_suspended_depot_is_still_not_found(self, setup, customer):
        order = make_order_in_state(setup, customer, OrderStatus.PENDING)
        other = make_order_setup()
        other.depot.status = DepotStatus.SUSPENDED
        other.depot.save(update_fields=["status"])
        with pytest.raises(NotFoundDomainError):
            invoke("accept", setup, customer, order, at(10, 10), actor=other.manager, depot=other.depot)
        assert reload(order).status == OrderStatus.PENDING

    def test_own_depot_explicit_is_accepted(self, setup, customer):
        order = make_order_in_state(setup, customer, OrderStatus.PENDING)
        result = invoke("accept", setup, customer, order, at(10, 10), depot=setup.depot)
        assert result.status == OrderStatus.CONFIRMED


# =========================================================================== #
# 2. accept_order
# =========================================================================== #
class TestAcceptOrder:
    def test_nominal(self, setup, customer):
        order = place_order(setup, customer, quantity=2)
        now = at(10, 5)
        result = order_services.accept_order(order=order, actor=setup.manager, now=now)

        order = reload(result)
        assert order.status == OrderStatus.CONFIRMED
        assert order.confirmed_at == now
        assert order.pickup_deadline_at == now + timedelta(hours=2)
        reservation = StockReservation.objects.get(order=order)
        assert reservation.status == StockReservationStatus.ACTIVE
        assert reservation.expires_at == order.pickup_deadline_at
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (10, 2)
        assert [(h.from_status, h.to_status) for h in history_of(order)] == [
            ("", OrderStatus.PENDING),
            (OrderStatus.PENDING, OrderStatus.CONFIRMED),
        ]
        assert movements(StockMovementType.RELEASE).count() == 0

    @pytest.mark.parametrize(
        ("accept_at", "expected"),
        [
            (at(10, 5), at(12, 5)),
            (at(17, 59), at(19, 59)),
            (at(18, 0), at(20, 0)),
            (at(19, 10), at(20, 0)),  # borné à l'heure de fermeture
        ],
        ids=["standard", "just-before-cap", "exactly-cap", "capped-by-closing"],
    )
    def test_pickup_deadline_is_capped_by_closing_time(self, setup, customer, accept_at, expected):
        order = place_order(setup, customer, now=accept_at - 5 * MIN)
        order_services.accept_order(order=order, actor=setup.manager, now=accept_at)
        order = reload(order)
        assert order.pickup_deadline_at == expected
        assert StockReservation.objects.get(order=order).expires_at == expected

    @pytest.mark.parametrize("status", [DepotStatus.SUSPENDED, DepotStatus.DISABLED])
    def test_depot_not_editable(self, setup, customer, status):
        order = place_order(setup, customer)
        setup.depot.status = status
        setup.depot.save(update_fields=["status"])
        with pytest.raises(ForbiddenDomainError) as exc:
            order_services.accept_order(order=order, actor=setup.manager, now=at(10, 5))
        assert_domain_error(exc, ForbiddenDomainError, "DEPOT_NOT_EDITABLE")
        assert reload(order).status == OrderStatus.PENDING


# =========================================================================== #
# 3. refuse_order
# =========================================================================== #
class TestRefuseOrder:
    def test_nominal(self, setup, customer):
        order = place_order(setup, customer, quantity=2)
        now = at(10, 5)
        order_services.refuse_order(
            order=order, actor=setup.manager, reason="Rupture de stock", now=now
        )
        order = reload(order)
        assert order.status == OrderStatus.REFUSED
        assert order.refused_at == now
        assert order.status_reason == "Rupture de stock"
        assert order.counted_as_no_show is False
        reservation = StockReservation.objects.get(order=order)
        assert reservation.status == StockReservationStatus.RELEASED
        assert reservation.released_at is not None
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (10, 0)
        assert movements(StockMovementType.RELEASE).get().delta == 2
        assert history_of(order)[-1].to_status == OrderStatus.REFUSED

    @pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
    def test_reason_is_required(self, setup, customer, reason):
        order = place_order(setup, customer, quantity=2)
        with pytest.raises(ValidationDomainError):
            order_services.refuse_order(
                order=order, actor=setup.manager, reason=reason, now=at(10, 5)
            )
        assert reload(order).status == OrderStatus.PENDING
        assert stock_of(setup.depot, setup.product).reserved_quantity == 2


# =========================================================================== #
# 4. cancel_order_by_customer
# =========================================================================== #
class TestCancelByCustomer:
    @pytest.mark.parametrize("state", [OrderStatus.PENDING, OrderStatus.CONFIRMED])
    def test_nominal(self, setup, customer, state):
        order = make_order_in_state(setup, customer, state, quantity=2)
        now = at(10, 10)
        order_services.cancel_order_by_customer(
            order=order, customer=customer, reason="Changement de plan", now=now
        )
        order = reload(order)
        assert order.status == OrderStatus.CANCELLED
        assert order.cancelled_at == now
        assert order.cancellation_source == OrderCancellationSource.CUSTOMER
        assert order.counted_as_no_show is False
        assert order.status_reason == "Changement de plan"
        assert StockReservation.objects.get(order=order).status == StockReservationStatus.RELEASED
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (10, 0)
        assert movements(StockMovementType.RELEASE).get().delta == 2
        assert history_of(order)[-1].to_status == OrderStatus.CANCELLED

    def test_reason_is_optional(self, setup, customer):
        order = place_order(setup, customer)
        order_services.cancel_order_by_customer(order=order, customer=customer, now=at(10, 5))
        order = reload(order)
        assert order.status == OrderStatus.CANCELLED
        assert not order.status_reason

    def test_other_customer_is_not_found(self, setup, customer, other_customer):
        order = place_order(setup, customer)
        with pytest.raises(NotFoundDomainError):
            order_services.cancel_order_by_customer(
                order=order, customer=other_customer, now=at(10, 5)
            )
        assert reload(order).status == OrderStatus.PENDING
        assert stock_of(setup.depot, setup.product).reserved_quantity == 1


# =========================================================================== #
# 5. cancel_order_non_conformity
# =========================================================================== #
class TestCancelNonConformity:
    def test_nominal(self, setup, customer):
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED, quantity=2)
        now = at(10, 20)
        order_services.cancel_order_non_conformity(
            order=order, actor=setup.manager, reason="Bouteille non conforme", now=now
        )
        order = reload(order)
        assert order.status == OrderStatus.CANCELLED
        assert order.cancelled_at == now
        assert order.cancellation_source == OrderCancellationSource.DEPOT_NON_CONFORMITY
        assert order.counted_as_no_show is False
        assert order.status_reason == "Bouteille non conforme"
        assert StockReservation.objects.get(order=order).status == StockReservationStatus.RELEASED
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (10, 0)
        assert movements(StockMovementType.RELEASE).get().delta == 2

    @pytest.mark.parametrize("reason", ["", "   "])
    def test_reason_is_required(self, setup, customer, reason):
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED)
        with pytest.raises(ValidationDomainError):
            order_services.cancel_order_non_conformity(
                order=order, actor=setup.manager, reason=reason, now=at(10, 20)
            )
        assert reload(order).status == OrderStatus.CONFIRMED


# =========================================================================== #
# 6. complete_pickup
# =========================================================================== #
def confirmed(setup, customer, **kwargs):
    return make_order_in_state(setup, customer, OrderStatus.CONFIRMED, **kwargs)


class TestCompletePickup:
    PICKUP_NOW = at(10, 30)

    def pickup(self, setup, order, **kwargs):
        kwargs.setdefault("payment_method", PaymentMethod.CASH)
        return order_services.complete_pickup(
            order=order, actor=setup.manager, now=self.PICKUP_NOW, **kwargs
        )

    def test_refill_cash_nominal(self, setup, customer):
        order = confirmed(setup, customer, quantity=2)
        self.pickup(setup, order)

        order = reload(order)
        assert order.status == OrderStatus.PICKED_UP
        assert order.picked_up_at == self.PICKUP_NOW
        assert order.payment_status == PaymentStatus.PAID

        payment = PaymentRecord.objects.get(order=order)
        assert payment.status == PaymentStatus.PAID
        assert payment.payment_method == PaymentMethod.CASH
        assert payment.expected_amount == payment.received_amount == Decimal("2000")

        reservation = StockReservation.objects.get(order=order)
        assert reservation.status == StockReservationStatus.CONSUMED
        assert reservation.consumed_at is not None

        full = stock_of(setup.depot, setup.product)
        assert (full.physical_quantity, full.reserved_quantity) == (8, 0)
        assert movements(StockMovementType.PICKUP_OUT).get().delta == -2
        assert movements(StockMovementType.RELEASE).count() == 0
        assert history_of(order)[-1].to_status == OrderStatus.PICKED_UP

    def test_refill_creates_empty_stock(self, setup, customer):
        order = confirmed(setup, customer, quantity=2)
        self.pickup(setup, order)
        empty = stock_of(setup.depot, setup.product, StockCategory.EMPTY)
        assert empty.physical_quantity == 2
        assert movements(StockMovementType.EMPTY_RETURN).get().delta == 2

    def test_refill_increments_existing_empty_stock(self, setup, customer):
        make_stock(
            depot=setup.depot,
            product=setup.product,
            category=StockCategory.EMPTY,
            physical_quantity=3,
        )
        order = confirmed(setup, customer, quantity=2)
        self.pickup(setup, order)
        assert stock_of(setup.depot, setup.product, StockCategory.EMPTY).physical_quantity == 5

    def test_mobile_money_with_reference_and_notes(self, setup, customer):
        order = confirmed(setup, customer)
        self.pickup(
            setup,
            order,
            payment_method=PaymentMethod.MOBILE_MONEY,
            external_reference="MM-123456",
            notes="Payé à la remise",
        )
        payment = PaymentRecord.objects.get(order=order)
        assert payment.payment_method == PaymentMethod.MOBILE_MONEY
        assert payment.external_reference == "MM-123456"
        assert payment.notes == "Payé à la remise"
        assert payment.status == PaymentStatus.PAID
        assert payment.paid_at is not None

    def test_explicit_matching_received_amount(self, setup, customer):
        order = confirmed(setup, customer, quantity=2)
        self.pickup(setup, order, received_amount=2000)
        assert PaymentRecord.objects.get(order=order).received_amount == 2000

    @pytest.mark.parametrize("received", [Decimal("0"), Decimal("1999"), Decimal("2001")])
    def test_received_amount_must_match_total(self, setup, customer, received):
        order = confirmed(setup, customer, quantity=2)
        with pytest.raises(ValidationDomainError):
            self.pickup(setup, order, received_amount=received)
        order = reload(order)
        assert order.status == OrderStatus.CONFIRMED
        assert order.payment_status == PaymentStatus.PENDING
        assert not PaymentRecord.objects.filter(order=order).exists()
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (10, 2)
        assert movements(StockMovementType.PICKUP_OUT).count() == 0

    @pytest.mark.parametrize("method", ["CARD", "BITCOIN", ""])
    def test_invalid_payment_method(self, setup, customer, method):
        order = confirmed(setup, customer)
        with pytest.raises(ValidationDomainError):
            self.pickup(setup, order, payment_method=method)
        assert reload(order).status == OrderStatus.CONFIRMED
        assert not PaymentRecord.objects.filter(order=order).exists()

    def test_exchange_returns_empty_of_exchanged_brand_same_capacity(self, setup, customer):
        order = confirmed(setup, customer, operation_type=OperationType.EXCHANGE, quantity=2)
        self.pickup(setup, order)

        assert PaymentRecord.objects.get(order=order).expected_amount == Decimal("3000")
        empty = stock_of(setup.depot, setup.exchange_product, StockCategory.EMPTY)
        assert empty.physical_quantity == 2
        assert not DepotStock.objects.filter(
            depot=setup.depot, product=setup.product, category=StockCategory.EMPTY
        ).exists()
        assert movements(StockMovementType.EMPTY_RETURN).get().delta == 2
        assert stock_of(setup.depot, setup.product).physical_quantity == 8

    def test_first_acquisition_has_no_empty_return(self, customer):
        setup = make_order_setup(new_physical=5)
        make_stock(
            depot=setup.depot,
            product=setup.product,
            category=StockCategory.EMPTY,
            physical_quantity=4,
        )
        order = confirmed(
            setup, customer, operation_type=OperationType.FIRST_ACQUISITION, quantity=2
        )
        self.pickup(setup, order)

        assert PaymentRecord.objects.get(order=order).expected_amount == Decimal("16000")
        new = stock_of(setup.depot, setup.product, StockCategory.NEW)
        assert (new.physical_quantity, new.reserved_quantity) == (3, 0)
        assert stock_of(setup.depot, setup.product, StockCategory.FULL).physical_quantity == 10
        assert stock_of(setup.depot, setup.product, StockCategory.EMPTY).physical_quantity == 4
        assert movements(StockMovementType.EMPTY_RETURN).count() == 0

    def test_double_pickup_does_not_decrement_twice(self, setup, customer):
        order = confirmed(setup, customer, quantity=2)
        self.pickup(setup, order)
        with pytest.raises(ConflictDomainError) as exc:
            self.pickup(setup, reload(order))
        assert_domain_error(exc, ConflictDomainError, "INVALID_ORDER_TRANSITION")
        assert stock_of(setup.depot, setup.product).physical_quantity == 8
        assert movements(StockMovementType.PICKUP_OUT).count() == 1
        assert PaymentRecord.objects.filter(order=order).count() == 1


# =========================================================================== #
# 7. expire_order
# =========================================================================== #
class TestExpireOrder:
    def test_pending_overdue(self, setup, customer):
        order = place_order(setup, customer, quantity=2)
        result, changed = order_services.expire_order(order=order, now=at(10, 16))
        assert changed is True
        order = reload(result)
        assert order.status == OrderStatus.EXPIRED
        assert order.counted_as_no_show is False
        assert order.expired_at is not None
        assert StockReservation.objects.get(order=order).status == StockReservationStatus.RELEASED
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (10, 0)
        assert movements(StockMovementType.RELEASE).get().delta == 2
        assert history_of(order)[-1].to_status == OrderStatus.EXPIRED

    def test_confirmed_overdue_is_a_no_show(self, setup, customer):
        order = confirmed(setup, customer, quantity=2)  # retrait limite 12:05
        result, changed = order_services.expire_order(order=order, now=at(12, 6))
        assert changed is True
        order = reload(result)
        assert order.status == OrderStatus.EXPIRED
        assert order.counted_as_no_show is True
        assert stock_of(setup.depot, setup.product).reserved_quantity == 0

    @pytest.mark.parametrize(
        ("state", "now"),
        [(OrderStatus.PENDING, at(10, 15)), (OrderStatus.CONFIRMED, at(12, 5))],
        ids=["pending-at-deadline", "confirmed-at-deadline"],
    )
    def test_not_yet_overdue_is_untouched(self, setup, customer, state, now):
        order = make_order_in_state(setup, customer, state, quantity=2)
        result, changed = order_services.expire_order(order=order, now=now)
        assert changed is False
        assert reload(result).status == state
        assert stock_of(setup.depot, setup.product).reserved_quantity == 2
        assert movements(StockMovementType.RELEASE).count() == 0

    def test_is_idempotent(self, setup, customer):
        order = place_order(setup, customer, quantity=2)
        _, first = order_services.expire_order(order=order, now=at(10, 16))
        again, second = order_services.expire_order(order=reload(order), now=at(10, 30))
        third_order, third = order_services.expire_order(order=order, now=at(11, 0))  # instance périmée
        assert (first, second, third) == (True, False, False)
        assert reload(again).status == OrderStatus.EXPIRED
        assert movements(StockMovementType.RELEASE).count() == 1
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (10, 0)

    @pytest.mark.parametrize(
        "state",
        [OrderStatus.PICKED_UP, OrderStatus.REFUSED, OrderStatus.CANCELLED],
    )
    def test_final_orders_are_never_expired(self, setup, customer, state):
        order = make_order_in_state(setup, customer, state)
        result, changed = order_services.expire_order(order=order, now=at(18, 0))
        assert changed is False
        assert reload(result).status == state

    def test_customer_can_order_again_after_expiration(self, setup, customer):
        order = place_order(setup, customer)
        order_services.expire_order(order=order, now=at(10, 16))
        assert place_order(setup, customer, now=at(10, 17)).status == OrderStatus.PENDING