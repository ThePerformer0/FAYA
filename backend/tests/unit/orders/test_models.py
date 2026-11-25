"""Jalon 3 / Lot 1 — contrats modèles et contraintes SQL (boîte noire).

Principe : on fabrique un état VALIDE via les services publics, puis on tente de
le corrompre avec ``QuerySet.update()`` dans un ``transaction.atomic()`` pour
vérifier que c'est bien PostgreSQL (CheckConstraint / index partiel / trigger)
qui refuse, indépendamment de la couche Python.
"""
import re
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import ProtectedError

from apps.core.exceptions import ValidationDomainError
from apps.depots.models import OperationType
from apps.inventory.models import (
    StockCategory,
    StockMovementType,
    StockReservation,
    StockReservationStatus,
)
from apps.orders.models import (
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentMethod,
    PaymentRecord,
    PaymentStatus,
)
from tests.factories_inventory import make_stock
from tests.factories_catalog import make_brand
from tests.factories_orders import (
    BASE_NOW,
    at,
    clone_instance,
    history_of,
    make_cancelled_orders,
    make_order_in_state,
    make_order_setup,
    place_order,
)

pytestmark = pytest.mark.django_db

ACTIVE_INDEX = "orders_unique_active_order_per_customer"


@pytest.fixture
def setup():
    return make_order_setup()


@pytest.fixture
def order(setup, customer):
    return place_order(setup, customer, quantity=1)


def assert_db_rejects(model, pk, **changes):
    """Le SGBD doit refuser la mise à jour (et la transaction de test reste saine)."""
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            model.objects.filter(pk=pk).update(**changes)


# --------------------------------------------------------------------------- #
# Order
# --------------------------------------------------------------------------- #
class TestOrder:
    def test_defaults_after_creation(self, order, customer, setup):
        assert order.status == OrderStatus.PENDING
        assert order.payment_status == PaymentStatus.PENDING
        assert order.customer_id == customer.pk
        assert order.depot_id == setup.depot.pk
        assert order.counted_as_no_show is False
        assert order.pickup_deadline_at is None
        assert order.confirmed_at is None and order.picked_up_at is None
        assert order.refused_at is None and order.cancelled_at is None
        assert order.expired_at is None

    def test_reference_format(self, order):
        assert re.fullmatch(r"FAY-[A-Z0-9]{6}", order.reference)

    def test_references_are_distinct_between_orders(self, setup, customer, other_customer):
        first = place_order(setup, customer)
        second = place_order(setup, other_customer)
        assert first.reference != second.reference

    def test_reference_is_unique_in_database(self, setup, customer):
        # Commande FINALE : seul l'unicité de ``reference`` peut être en cause.
        final = make_order_in_state(setup, customer, OrderStatus.CANCELLED)
        duplicate = clone_instance(final)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                duplicate.save()

    def test_negative_total_amount_rejected(self, order):
        assert_db_rejects(Order, order.pk, total_amount=Decimal("-1"))

    def test_zero_total_amount_is_allowed_by_constraint(self, order):
        with transaction.atomic():
            Order.objects.filter(pk=order.pk).update(total_amount=Decimal("0"))

    def test_confirmed_requires_pickup_deadline(self, order):
        assert_db_rejects(
            Order, order.pk, status=OrderStatus.CONFIRMED, pickup_deadline_at=None
        )

    def test_confirmed_with_pickup_deadline_is_accepted(self, order):
        with transaction.atomic():
            Order.objects.filter(pk=order.pk).update(
                status=OrderStatus.CONFIRMED, pickup_deadline_at=at(12, 0)
            )
        assert Order.objects.get(pk=order.pk).status == OrderStatus.CONFIRMED

    @pytest.mark.parametrize("first_state", [OrderStatus.PENDING, OrderStatus.CONFIRMED])
    def test_partial_unique_index_forbids_two_active_orders(
        self, setup, customer, other_customer, first_state
    ):
        make_order_in_state(setup, customer, first_state)
        second = place_order(setup, other_customer)
        with pytest.raises(IntegrityError) as excinfo:
            with transaction.atomic():
                # On « rattache » la 2e commande active au client déjà actif.
                Order.objects.filter(pk=second.pk).update(customer=customer)
        assert ACTIVE_INDEX in str(excinfo.value)

    def test_partial_unique_index_allows_many_final_orders(self, setup, customer):
        make_cancelled_orders(setup, customer, 2)
        make_order_in_state(setup, customer, OrderStatus.REFUSED)
        make_order_in_state(setup, customer, OrderStatus.EXPIRED)
        make_order_in_state(setup, customer, OrderStatus.PICKED_UP)
        assert (
            Order.objects.filter(customer=customer)
            .exclude(status__in=[OrderStatus.PENDING, OrderStatus.CONFIRMED])
            .count()
            == 5
        )

    def test_final_orders_do_not_block_a_new_active_order(self, setup, customer):
        make_cancelled_orders(setup, customer, 2)
        active = place_order(setup, customer)
        assert active.status == OrderStatus.PENDING
        assert Order.objects.filter(customer=customer).count() == 3

    def test_two_customers_can_each_have_an_active_order(
        self, setup, customer, other_customer
    ):
        place_order(setup, customer)
        place_order(setup, other_customer)
        assert Order.objects.filter(status=OrderStatus.PENDING).count() == 2

    def test_customer_is_protected(self, order, customer):
        with pytest.raises(ProtectedError) as excinfo:
            customer.delete()
        assert any(isinstance(o, Order) for o in excinfo.value.protected_objects)

    def test_depot_is_protected(self, order, setup):
        with pytest.raises(ProtectedError) as excinfo:
            setup.depot.delete()
        assert any(isinstance(o, Order) for o in excinfo.value.protected_objects)


# --------------------------------------------------------------------------- #
# OrderItem
# --------------------------------------------------------------------------- #
class TestOrderItem:
    def test_refill_item_snapshot(self, setup, customer):
        order = place_order(setup, customer, quantity=3)
        item = OrderItem.objects.get(order=order)
        assert item.operation_type == OperationType.REFILL
        assert item.quantity == 3
        assert item.unit_gas_price == Decimal("1000")
        assert item.unit_bottle_price == 0
        assert item.unit_deposit_amount == 0
        assert item.unit_total_price == Decimal("1000")
        assert item.line_total_amount == Decimal("3000")
        assert item.exchange_brand_id is None
        assert order.total_amount == Decimal("3000")

    def test_exchange_item_references_brand(self, setup, customer):
        order = place_order(setup, customer, operation_type=OperationType.EXCHANGE, quantity=2)
        item = OrderItem.objects.get(order=order)
        assert item.exchange_brand_id == setup.exchange_brand.pk
        assert item.unit_total_price == Decimal("1500")
        assert item.line_total_amount == Decimal("3000")

    def test_first_acquisition_item_may_carry_bottle_and_deposit(self, setup, customer):
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

    @pytest.mark.parametrize(
        "changes",
        [
            # quantité < 1 (en gardant les montants cohérents : seule cette contrainte saute)
            {"quantity": 0, "line_total_amount": Decimal("0")},
            {"quantity": -1, "line_total_amount": Decimal("-1000")},
            # unit_total_price != gaz + bouteille + consigne
            {"unit_total_price": Decimal("1001"), "line_total_amount": Decimal("1001")},
            # line_total_amount != unit_total_price * quantity
            {"line_total_amount": Decimal("1")},
            # bouteille / consigne non nulles hors FIRST_ACQUISITION
            {
                "unit_bottle_price": Decimal("500"),
                "unit_total_price": Decimal("1500"),
                "line_total_amount": Decimal("1500"),
            },
            {
                "unit_deposit_amount": Decimal("500"),
                "unit_total_price": Decimal("1500"),
                "line_total_amount": Decimal("1500"),
            },
        ],
        ids=[
            "quantity-zero", "quantity-negative", "unit-total-mismatch",
            "line-total-mismatch", "bottle-price-on-refill", "deposit-on-refill",
        ],
    )
    def test_item_check_constraints(self, order, changes):
        item = OrderItem.objects.get(order=order)
        assert_db_rejects(OrderItem, item.pk, **changes)

    def test_refill_item_cannot_have_exchange_brand(self, order):
        item = OrderItem.objects.get(order=order)
        assert_db_rejects(OrderItem, item.pk, exchange_brand=make_brand())

    def test_exchange_item_requires_exchange_brand(self, setup, customer):
        order = place_order(setup, customer, operation_type=OperationType.EXCHANGE)
        item = OrderItem.objects.get(order=order)
        assert_db_rejects(OrderItem, item.pk, exchange_brand=None)


# --------------------------------------------------------------------------- #
# StockReservation
# --------------------------------------------------------------------------- #
class TestStockReservation:
    @pytest.fixture
    def reservation(self, order):
        return StockReservation.objects.get(order=order)

    def test_created_active(self, reservation, order):
        assert reservation.status == StockReservationStatus.ACTIVE
        assert reservation.quantity == 1
        assert reservation.released_at is None and reservation.consumed_at is None

    def test_unique_order_stock(self, reservation):
        duplicate = clone_instance(reservation)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                duplicate.save()

    def test_quantity_must_be_positive(self, reservation):
        assert_db_rejects(StockReservation, reservation.pk, quantity=0)

    def test_released_requires_released_at(self, reservation):
        assert_db_rejects(
            StockReservation,
            reservation.pk,
            status=StockReservationStatus.RELEASED,
            released_at=None,
        )

    def test_consumed_requires_consumed_at(self, reservation):
        assert_db_rejects(
            StockReservation,
            reservation.pk,
            status=StockReservationStatus.CONSUMED,
            consumed_at=None,
        )

    def test_released_with_timestamp_is_accepted(self, reservation):
        with transaction.atomic():
            StockReservation.objects.filter(pk=reservation.pk).update(
                status=StockReservationStatus.RELEASED, released_at=BASE_NOW
            )

    def test_consumed_with_timestamp_is_accepted(self, reservation):
        with transaction.atomic():
            StockReservation.objects.filter(pk=reservation.pk).update(
                status=StockReservationStatus.CONSUMED, consumed_at=BASE_NOW
            )

    def test_clean_accepts_genuine_reservation(self, reservation):
        reservation.clean()

    def test_clean_refuses_empty_stock(self, reservation, setup):
        empty = make_stock(
            depot=setup.depot,
            product=setup.product,
            category=StockCategory.EMPTY,
            physical_quantity=5,
        )
        candidate = clone_instance(reservation)
        candidate.stock = empty
        with pytest.raises((DjangoValidationError, ValidationDomainError)):
            candidate.clean()

    @pytest.mark.parametrize("quantity", [0, -1])
    def test_clean_refuses_non_positive_quantity(self, reservation, quantity):
        candidate = clone_instance(reservation)
        candidate.quantity = quantity
        with pytest.raises((DjangoValidationError, ValidationDomainError)):
            candidate.clean()


# --------------------------------------------------------------------------- #
# OrderStatusHistory — immuabilité stricte (Python + PostgreSQL)
# --------------------------------------------------------------------------- #
class TestOrderStatusHistoryImmutability:
    @pytest.fixture
    def entry(self, order):
        entries = history_of(order)
        assert len(entries) == 1
        return entries[0]

    def test_creation_writes_initial_entry(self, entry):
        assert entry.from_status == ""
        assert entry.to_status == OrderStatus.PENDING

    def test_append_only_inserts_are_allowed(self, entry, order):
        clone_instance(entry).save()
        OrderStatusHistory.objects.bulk_create([clone_instance(entry)])
        assert OrderStatusHistory.objects.filter(order=order).count() == 3

    def test_save_on_existing_row_raises(self, entry):
        entry.to_status = OrderStatus.CONFIRMED
        with pytest.raises(PermissionError):
            entry.save()

    def test_delete_raises(self, entry):
        with pytest.raises(PermissionError):
            entry.delete()

    def test_queryset_update_raises(self, entry):
        with pytest.raises(PermissionError):
            OrderStatusHistory.objects.filter(pk=entry.pk).update(
                to_status=OrderStatus.CONFIRMED
            )

    def test_queryset_delete_raises(self, entry):
        with pytest.raises(PermissionError):
            OrderStatusHistory.objects.filter(pk=entry.pk).delete()

    def test_bulk_update_raises(self, entry):
        entry.to_status = OrderStatus.CONFIRMED
        with pytest.raises(PermissionError):
            OrderStatusHistory.objects.bulk_update([entry], ["to_status"])

    def test_bulk_create_with_update_conflicts_raises(self, entry):
        entry.to_status = OrderStatus.CONFIRMED
        with pytest.raises(PermissionError):
            OrderStatusHistory.objects.bulk_create(
                [entry],
                update_conflicts=True,
                update_fields=["to_status"],
                unique_fields=[OrderStatusHistory._meta.pk.name],
            )

    def test_raw_sql_update_blocked_by_trigger(self, entry):
        table = OrderStatusHistory._meta.db_table
        pk_col = OrderStatusHistory._meta.pk.column
        with pytest.raises(DatabaseError):  # IntegrityError hérite de DatabaseError
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f'UPDATE "{table}" SET to_status = %s WHERE "{pk_col}" = %s',
                        [OrderStatus.CONFIRMED, entry.pk],
                    )
        entry.refresh_from_db()
        assert entry.to_status == OrderStatus.PENDING

    def test_raw_sql_delete_blocked_by_trigger(self, entry):
        table = OrderStatusHistory._meta.db_table
        pk_col = OrderStatusHistory._meta.pk.column
        with pytest.raises(DatabaseError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        f'DELETE FROM "{table}" WHERE "{pk_col}" = %s', [entry.pk]
                    )
        assert OrderStatusHistory.objects.filter(pk=entry.pk).exists()

    def test_order_fk_is_protected(self, order, entry):
        with pytest.raises(ProtectedError) as excinfo:
            order.delete()
        assert any(
            isinstance(o, OrderStatusHistory) for o in excinfo.value.protected_objects
        )


# --------------------------------------------------------------------------- #
# PaymentRecord
# --------------------------------------------------------------------------- #
class TestPaymentRecord:
    @pytest.fixture
    def picked_up(self, setup, customer):
        return make_order_in_state(setup, customer, OrderStatus.PICKED_UP, quantity=2)

    @pytest.fixture
    def payment(self, picked_up):
        return PaymentRecord.objects.get(order=picked_up)

    def test_no_payment_before_pickup(self, order):
        assert not PaymentRecord.objects.filter(order=order).exists()

    def test_payment_content(self, payment, picked_up):
        assert payment.expected_amount == picked_up.total_amount == Decimal("2000")
        assert payment.received_amount == Decimal("2000")
        assert payment.payment_method == PaymentMethod.CASH

    def test_one_to_one_with_order(self, payment):
        duplicate = clone_instance(payment)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                duplicate.save()

    def test_expected_amount_non_negative(self, payment):
        assert_db_rejects(PaymentRecord, payment.pk, expected_amount=Decimal("-1"))

    def test_received_amount_non_negative(self, payment):
        assert_db_rejects(PaymentRecord, payment.pk, received_amount=Decimal("-1"))

    def test_order_fk_is_protected(self, picked_up):
        with pytest.raises(ProtectedError) as excinfo:
            picked_up.delete()
        assert any(isinstance(o, PaymentRecord) for o in excinfo.value.protected_objects)


def test_stock_movement_reservation_is_recorded(setup, customer):
    """Garde-fou : la création d'une commande journalise bien une RESERVATION."""
    from tests.factories_orders import movements

    place_order(setup, customer, quantity=2)
    movement = movements(StockMovementType.RESERVATION).get()
    assert movement.delta == -2