"""Jalon 3 / Lot 3 — concurrence réelle PostgreSQL (multi-thread, vraies transactions).

Chaque scénario lance ses appels simultanément via ``run_concurrently`` (barrière de
synchronisation + fermeture des connexions de chaque thread). Les appels sont encapsulés
par ``attempt`` : un thread ne lève jamais, il rapporte ``("ok", valeur)`` ou
``("err", exception)``, ce qui permet de compter exactement succès et échecs.

Toutes les dates métier sont explicites (``now=``) : aucune dépendance à l'horloge réelle.
"""
import pytest

from apps.accounts.models import UserRole
from apps.core.exceptions import ConflictDomainError
from apps.depots.models import OperationType
from apps.inventory.models import (
    StockCategory,
    StockMovementType,
    StockReservation,
    StockReservationStatus,
)
from apps.orders import services as order_services
from apps.orders.models import Order, OrderStatus, PaymentMethod, PaymentRecord
from tests.concurrency_helpers import run_concurrently
from tests.factories_orders import (
    BASE_NOW,
    at,
    available,
    error_code,
    make_customers,
    make_order_in_state,
    make_order_setup,
    movements,
    place_order,
    stock_of,
)
from tests.helpers import create_user

pytestmark = pytest.mark.django_db(transaction=True)

ROUNDS = range(5)  # on répète les courses pour couvrir plusieurs entrelacements


@pytest.fixture(autouse=True)
def _platform(platform_setting):
    return platform_setting


def attempt(fn):
    """Retourne le callable tel quel : ``run_concurrently`` capture déjà (\"ok\"|\"err\", valeur)."""
    return fn


def oks(results):
    return [value for kind, value in results if kind == "ok"]


def errs(results):
    return [value for kind, value in results if kind == "err"]


def create_callable(setup, customer, *, quantity=1, operation_type=OperationType.REFILL):
    return attempt(
        lambda: place_order(
            setup, customer, quantity=quantity, operation_type=operation_type, now=BASE_NOW
        )
    )


# --------------------------------------------------------------------------- #
# 1. Dernière bouteille disputée
# --------------------------------------------------------------------------- #
def test_last_bottle_is_given_to_exactly_one_customer():
    setup = make_order_setup(physical=1, reserved=0)
    customers = make_customers(4)

    results = run_concurrently([create_callable(setup, c) for c in customers])

    assert len(oks(results)) == 1
    failures = errs(results)
    assert len(failures) == 3
    for exc in failures:
        assert isinstance(exc, ConflictDomainError), repr(exc)
        assert error_code(exc) == "INSUFFICIENT_STOCK"

    stock = stock_of(setup.depot, setup.product)
    assert (stock.physical_quantity, stock.reserved_quantity, available(stock)) == (1, 1, 0)
    assert Order.objects.count() == 1
    assert StockReservation.objects.filter(status=StockReservationStatus.ACTIVE).count() == 1
    assert movements(StockMovementType.RESERVATION).count() == 1


def test_stock_is_shared_without_overselling():
    """5 disponibles, 4 clients x 2 bouteilles : exactement 2 gagnants, jamais de survente."""
    setup = make_order_setup(physical=5)
    customers = make_customers(4)

    results = run_concurrently([create_callable(setup, c, quantity=2) for c in customers])

    assert len(oks(results)) == 2
    assert {error_code(e) for e in errs(results)} == {"INSUFFICIENT_STOCK"}
    stock = stock_of(setup.depot, setup.product)
    assert stock.reserved_quantity == 4
    assert available(stock) == 1
    assert Order.objects.count() == 2


def test_ample_stock_lets_everyone_through_without_lost_update():
    setup = make_order_setup(physical=10)
    customers = make_customers(4)

    results = run_concurrently([create_callable(setup, c) for c in customers])

    assert len(oks(results)) == 4 and not errs(results)
    assert stock_of(setup.depot, setup.product).reserved_quantity == 4
    assert movements(StockMovementType.RESERVATION).count() == 4


# --------------------------------------------------------------------------- #
# 2. Double création par le même client
# --------------------------------------------------------------------------- #
def test_same_customer_cannot_create_two_active_orders():
    setup = make_order_setup(physical=10)
    customer = create_user(role=UserRole.CUSTOMER)

    results = run_concurrently(
        [create_callable(setup, customer, quantity=2) for _ in range(4)]
    )

    assert len(oks(results)) == 1
    failures = errs(results)
    assert len(failures) == 3
    for exc in failures:
        assert isinstance(exc, ConflictDomainError), repr(exc)
        assert error_code(exc) == "ACTIVE_ORDER_EXISTS"

    assert Order.objects.filter(customer=customer).count() == 1
    assert stock_of(setup.depot, setup.product).reserved_quantity == 2
    assert movements(StockMovementType.RESERVATION).count() == 1


# --------------------------------------------------------------------------- #
# 3. Acceptation vs expiration au moment limite
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("round_", ROUNDS)
def test_accept_vs_expire_has_a_single_coherent_winner(round_):
    setup = make_order_setup()
    customer = create_user(role=UserRole.CUSTOMER)
    order = place_order(setup, customer, quantity=2, now=BASE_NOW)
    pk = order.pk
    deadline = order.response_deadline_at  # 10:15

    def do_accept():
        return order_services.accept_order(
            order=Order.objects.get(pk=pk), actor=setup.manager, now=deadline
        )

    def do_expire():
        # Une seconde après l'échéance : l'expiration est légitime.
        return order_services.expire_order(
            order=Order.objects.get(pk=pk), now=deadline.replace(second=1)
        )

    accept_result, expire_result = run_concurrently([attempt(do_accept), attempt(do_expire)])

    final = Order.objects.get(pk=pk)
    stock = stock_of(setup.depot, setup.product)
    reservation = StockReservation.objects.get(order=final)

    assert final.status in {OrderStatus.CONFIRMED, OrderStatus.EXPIRED}
    # Aucune exception inattendue côté expiration (idempotente) ; aucun deadlock (on est revenu).
    assert expire_result[0] == "ok", repr(expire_result[1])
    _, changed = expire_result[1]

    if final.status == OrderStatus.CONFIRMED:
        assert accept_result[0] == "ok"
        assert changed is False
        assert stock.reserved_quantity == 2
        assert reservation.status == StockReservationStatus.ACTIVE
        assert movements(StockMovementType.RELEASE).count() == 0
        assert final.pickup_deadline_at is not None
    else:
        assert accept_result[0] == "err"
        assert isinstance(accept_result[1], ConflictDomainError)
        assert error_code(accept_result[1]) in {"INVALID_ORDER_TRANSITION", "ORDER_EXPIRED"}
        assert changed is True
        assert stock.reserved_quantity == 0
        assert stock.physical_quantity == 10
        assert reservation.status == StockReservationStatus.RELEASED
        assert movements(StockMovementType.RELEASE).count() == 1
        assert final.counted_as_no_show is False


# --------------------------------------------------------------------------- #
# 4. Annulation client vs retrait simultanés
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("round_", ROUNDS)
def test_customer_cancel_vs_pickup_exactly_one_wins(round_):
    setup = make_order_setup()
    customer = create_user(role=UserRole.CUSTOMER)
    order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED, quantity=2)
    pk = order.pk
    now = at(10, 30)

    def do_cancel():
        return order_services.cancel_order_by_customer(
            order=Order.objects.get(pk=pk), customer=customer, now=now
        )

    def do_pickup():
        return order_services.complete_pickup(
            order=Order.objects.get(pk=pk),
            actor=setup.manager,
            payment_method=PaymentMethod.CASH,
            now=now,
        )

    results = run_concurrently([attempt(do_cancel), attempt(do_pickup)])

    assert len(oks(results)) == 1
    failures = errs(results)
    assert len(failures) == 1
    assert isinstance(failures[0], ConflictDomainError), repr(failures[0])
    assert error_code(failures[0]) == "INVALID_ORDER_TRANSITION"

    final = Order.objects.get(pk=pk)
    full = stock_of(setup.depot, setup.product)
    assert full.physical_quantity >= 0 and full.reserved_quantity >= 0
    assert full.reserved_quantity == 0

    if final.status == OrderStatus.CANCELLED:
        assert full.physical_quantity == 10
        assert movements(StockMovementType.RELEASE).count() == 1
        assert movements(StockMovementType.PICKUP_OUT).count() == 0
        assert movements(StockMovementType.EMPTY_RETURN).count() == 0
        assert not PaymentRecord.objects.filter(order=final).exists()
        assert StockReservation.objects.get(order=final).status == StockReservationStatus.RELEASED
    else:
        assert final.status == OrderStatus.PICKED_UP
        assert full.physical_quantity == 8
        assert movements(StockMovementType.PICKUP_OUT).count() == 1
        assert movements(StockMovementType.RELEASE).count() == 0
        assert movements(StockMovementType.EMPTY_RETURN).count() == 1
        assert stock_of(setup.depot, setup.product, StockCategory.EMPTY).physical_quantity == 2
        assert PaymentRecord.objects.filter(order=final).count() == 1
        assert StockReservation.objects.get(order=final).status == StockReservationStatus.CONSUMED


# --------------------------------------------------------------------------- #
# 5. Double expiration simultanée
# --------------------------------------------------------------------------- #
def test_concurrent_expiration_releases_stock_exactly_once():
    setup = make_order_setup()
    customer = create_user(role=UserRole.CUSTOMER)
    order = place_order(setup, customer, quantity=2, now=BASE_NOW)
    pk = order.pk
    late = at(10, 16)

    def do_expire():
        return order_services.expire_order(order=Order.objects.get(pk=pk), now=late)

    results = run_concurrently([attempt(do_expire) for _ in range(4)])

    assert not errs(results), [repr(e) for e in errs(results)]
    flags = [changed for _, changed in oks(results)]
    assert flags.count(True) == 1
    assert flags.count(False) == 3

    final = Order.objects.get(pk=pk)
    assert final.status == OrderStatus.EXPIRED
    assert final.counted_as_no_show is False
    assert movements(StockMovementType.RELEASE).count() == 1
    stock = stock_of(setup.depot, setup.product)
    assert (stock.physical_quantity, stock.reserved_quantity) == (10, 0)
    assert StockReservation.objects.get(order=final).status == StockReservationStatus.RELEASED