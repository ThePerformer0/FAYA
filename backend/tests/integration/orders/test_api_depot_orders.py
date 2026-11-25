"""Jalon 3 / Lot 4 — API responsable de dépôt ``/api/v1/depot/orders/...``.

Horloge figée à 10:00 (Africa/Douala). Le manager est TOUJOURS rattaché à son dépôt via
``make_order_setup(manager=depot_manager)`` (la fixture ``depot_manager`` seule n'a pas de dépôt).
"""
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils.dateparse import parse_datetime
from freezegun import freeze_time

from apps.depots.models import DepotStatus, OperationType
from apps.inventory.models import (
    StockCategory,
    StockMovementType,
    StockReservation,
    StockReservationStatus,
)
from apps.orders.models import (
    Order,
    OrderCancellationSource,
    OrderStatus,
    PaymentMethod,
    PaymentRecord,
    PaymentStatus,
)
from tests.factories_orders import (
    DEPOT_CUSTOMER_KEYS,
    DEPOT_ORDER_KEYS,
    FROZEN_ISO,
    NONEXISTENT_ID,
    ORDER_ITEM_KEYS,
    PAYMENT_KEYS,
    at,
    make_cancelled_orders,
    make_customers,
    make_order_in_state,
    make_order_setup,
    movements,
    place_order,
    stock_of,
)
from tests.helpers import assert_unified_error

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/depot/orders/"


def detail_url(order_id):
    return f"/api/v1/depot/orders/{order_id}/"


def action_url(order_id, action):
    return f"/api/v1/depot/orders/{order_id}/{action}/"


@pytest.fixture(autouse=True)
def _frozen_clock():
    with freeze_time(FROZEN_ISO):
        yield


@pytest.fixture(autouse=True)
def _platform(platform_setting):
    return platform_setting


@pytest.fixture
def setup(depot_manager):
    return make_order_setup(manager=depot_manager)


@pytest.fixture
def client(auth_client, depot_manager, setup):  # ``setup`` garantit le rattachement du dépôt
    return auth_client(depot_manager)


def assert_no_store(response):
    assert "no-store" in response["Cache-Control"]


def set_depot_status(setup, status):
    setup.depot.status = status
    setup.depot.save(update_fields=["status"])


# =========================================================================== #
# GET /api/v1/depot/orders/
# =========================================================================== #
class TestListDepotOrders:
    def test_paginated_and_exact_keys(self, client, setup, customer):
        place_order(setup, customer)
        response = client.get(LIST_URL)
        assert response.status_code == 200
        assert_no_store(response)
        body = response.json()
        assert set(body) == {"count", "next", "previous", "results"}
        assert body["count"] == 1
        result = body["results"][0]
        assert set(result) == DEPOT_ORDER_KEYS
        assert set(result["items"][0]) == ORDER_ITEM_KEYS
        assert set(result["customer"]) == DEPOT_CUSTOMER_KEYS
        assert result["customer"]["full_name"] == customer.full_name
        assert result["customer"]["phone"] == customer.phone

    def test_only_own_depot(self, client, setup, customer, other_customer):
        mine = place_order(setup, customer)
        other = make_order_setup()
        foreign = place_order(other, other_customer)

        ids = {str(r["id"]) for r in client.get(LIST_URL).json()["results"]}

        assert ids == {str(mine.pk)}
        assert str(foreign.pk) not in ids

    def test_pagination_page_size_is_20(self, client, setup, customer):
        make_cancelled_orders(setup, customer, 21)
        body = client.get(LIST_URL).json()
        assert body["count"] == 21 and len(body["results"]) == 20 and body["next"] is not None

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (OrderStatus.PENDING, 1),
            (OrderStatus.CANCELLED, 2),
            (OrderStatus.REFUSED, 1),
            (OrderStatus.CONFIRMED, 0),
        ],
    )
    def test_status_filter(self, client, setup, customer, status, expected):
        make_cancelled_orders(setup, customer, 2)
        make_order_in_state(setup, customer, OrderStatus.REFUSED)
        place_order(setup, customer, now=at(11, 0))
        body = client.get(LIST_URL, {"status": status}).json()
        assert body["count"] == expected
        assert all(r["status"] == status for r in body["results"])

    @pytest.mark.parametrize("value", ["", "NOPE", "pending"])
    def test_invalid_status_filter_is_400(self, client, value):
        response = client.get(LIST_URL, {"status": value})
        assert_unified_error(response, status=400)
        assert_no_store(response)

    def test_no_n_plus_one(self, client, setup):
        customers = make_customers(6)
        for c in customers[:2]:
            place_order(setup, c)
        with CaptureQueriesContext(connection) as small:
            assert client.get(LIST_URL).status_code == 200
        for c in customers[2:]:
            place_order(setup, c)
        with CaptureQueriesContext(connection) as large:
            response = client.get(LIST_URL)
        assert response.json()["count"] == 6
        assert len(large) == len(small)


# =========================================================================== #
# GET /api/v1/depot/orders/{id}/
# =========================================================================== #
class TestRetrieveDepotOrder:
    def test_own_depot_order(self, client, setup, customer):
        order = place_order(setup, customer)
        response = client.get(detail_url(order.pk))
        assert response.status_code == 200
        assert_no_store(response)
        body = response.json()
        assert set(body) == DEPOT_ORDER_KEYS
        assert set(body["customer"]) == DEPOT_CUSTOMER_KEYS
        assert str(body["id"]) == str(order.pk)

    def test_other_depot_order_is_404(self, client, other_customer):
        foreign = place_order(make_order_setup(), other_customer)
        assert_unified_error(client.get(detail_url(foreign.pk)), status=404, code="NOT_FOUND")

    def test_unknown_order_is_404(self, client):
        assert_unified_error(client.get(detail_url(NONEXISTENT_ID)), status=404, code="NOT_FOUND")


# =========================================================================== #
# POST .../accept/
# =========================================================================== #
class TestAccept:
    def test_accept(self, client, setup, customer):
        order = place_order(setup, customer, quantity=2, now=at(9, 55))
        response = client.post(action_url(order.pk, "accept"))

        assert response.status_code == 200
        assert_no_store(response)
        body = response.json()
        assert set(body) == DEPOT_ORDER_KEYS
        assert body["status"] == OrderStatus.CONFIRMED
        assert parse_datetime(body["pickup_deadline_at"]) == at(12, 0)  # 10:00 + 2 h
        assert parse_datetime(body["confirmed_at"]) == at(10, 0)
        assert [h["to_status"] for h in body["status_history"]] == [
            OrderStatus.PENDING,
            OrderStatus.CONFIRMED,
        ]
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (10, 2)

    def test_accept_pickup_deadline_capped_by_closing(self, auth_client, depot_manager, setup, customer):
        order = place_order(setup, customer, now=at(19, 5))
        with freeze_time("2026-03-04 19:10:00+01:00"):
            client = auth_client(depot_manager)
            body = client.post(action_url(order.pk, "accept")).json()
        assert parse_datetime(body["pickup_deadline_at"]) == at(20, 0)

    def test_accept_twice_is_409(self, client, setup, customer):
        order = place_order(setup, customer)
        assert client.post(action_url(order.pk, "accept")).status_code == 200
        response = client.post(action_url(order.pk, "accept"))
        assert_unified_error(response, status=409, code="INVALID_ORDER_TRANSITION")
        assert_no_store(response)

    def test_accept_overdue_is_409_and_persists_expiration(self, client, setup, customer):
        order = place_order(setup, customer, quantity=2, now=at(9, 40))  # échéance 09:55
        response = client.post(action_url(order.pk, "accept"))
        assert_unified_error(response, status=409, code="ORDER_EXPIRED")
        order = Order.objects.get(pk=order.pk)
        assert order.status == OrderStatus.EXPIRED
        assert order.counted_as_no_show is False
        assert stock_of(setup.depot, setup.product).reserved_quantity == 0

    @pytest.mark.parametrize("status", [DepotStatus.SUSPENDED, DepotStatus.DISABLED])
    def test_accept_on_non_editable_depot_is_403(self, client, setup, customer, status):
        order = place_order(setup, customer)
        set_depot_status(setup, status)
        response = client.post(action_url(order.pk, "accept"))
        assert_unified_error(response, status=403, code="DEPOT_NOT_EDITABLE")
        assert_no_store(response)
        assert Order.objects.get(pk=order.pk).status == OrderStatus.PENDING

    @pytest.mark.parametrize("status", [DepotStatus.ACTIVE, DepotStatus.SUSPENDED])
    def test_accept_foreign_order_is_404_even_if_own_depot_suspended(
        self, client, setup, other_customer, status
    ):
        foreign = place_order(make_order_setup(), other_customer)
        set_depot_status(setup, status)
        assert_unified_error(
            client.post(action_url(foreign.pk, "accept")), status=404, code="NOT_FOUND"
        )
        assert Order.objects.get(pk=foreign.pk).status == OrderStatus.PENDING


# =========================================================================== #
# POST .../refuse/
# =========================================================================== #
class TestRefuse:
    def test_refuse(self, client, setup, customer):
        order = place_order(setup, customer, quantity=2)
        response = client.post(action_url(order.pk, "refuse"), {"reason": "Rupture"}, format="json")
        assert response.status_code == 200
        assert_no_store(response)
        body = response.json()
        assert set(body) == DEPOT_ORDER_KEYS
        assert body["status"] == OrderStatus.REFUSED
        assert body["status_reason"] == "Rupture"
        assert body["refused_at"] is not None
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (10, 0)
        assert (
            StockReservation.objects.get(order=order).status == StockReservationStatus.RELEASED
        )
        assert movements(StockMovementType.RELEASE).get().delta == 2

    @pytest.mark.parametrize("data", [None, {}, {"reason": ""}, {"reason": "   "}, {"reason": None}])
    def test_reason_required(self, client, setup, customer, data):
        order = place_order(setup, customer)
        response = client.post(action_url(order.pk, "refuse"), data, format="json")
        assert_unified_error(response, status=400)
        assert Order.objects.get(pk=order.pk).status == OrderStatus.PENDING

    def test_refuse_confirmed_is_409(self, client, setup, customer):
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED)
        response = client.post(action_url(order.pk, "refuse"), {"reason": "x"}, format="json")
        assert_unified_error(response, status=409, code="INVALID_ORDER_TRANSITION")

    def test_refuse_foreign_order_is_404(self, client, other_customer):
        foreign = place_order(make_order_setup(), other_customer)
        response = client.post(action_url(foreign.pk, "refuse"), {"reason": "x"}, format="json")
        assert_unified_error(response, status=404, code="NOT_FOUND")


# =========================================================================== #
# POST .../pickup/
# =========================================================================== #
class TestPickup:
    def test_cash_without_amount_defaults_to_total(self, client, setup, customer):
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED, quantity=2)
        response = client.post(
            action_url(order.pk, "pickup"), {"payment_method": PaymentMethod.CASH}, format="json"
        )
        assert response.status_code == 200
        assert_no_store(response)
        body = response.json()
        assert set(body) == DEPOT_ORDER_KEYS
        assert body["status"] == OrderStatus.PICKED_UP
        assert body["payment_status"] == PaymentStatus.PAID
        assert set(body["payment"]) == PAYMENT_KEYS
        assert body["payment"]["payment_method"] == PaymentMethod.CASH
        assert body["payment"]["status"] == PaymentStatus.PAID
        assert Decimal(str(body["payment"]["received_amount"])) == Decimal("2000")
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (8, 0)
        assert stock_of(setup.depot, setup.product, StockCategory.EMPTY).physical_quantity == 2

    def test_mobile_money_with_reference_and_amount(self, client, setup, customer):
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED)
        response = client.post(
            action_url(order.pk, "pickup"),
            {
                "payment_method": PaymentMethod.MOBILE_MONEY,
                "received_amount": 1000,
                "external_reference": "MM-777",
                "notes": "Reçu OM",
            },
            format="json",
        )
        assert response.status_code == 200
        payment = response.json()["payment"]
        assert payment["payment_method"] == PaymentMethod.MOBILE_MONEY
        assert payment["external_reference"] == "MM-777"
        assert payment["notes"] == "Reçu OM"

    @pytest.mark.parametrize("amount", ["999", "1001", "0", "-5", "NaN", "abc"])
    def test_wrong_amount_is_400(self, client, setup, customer, amount):
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED)
        response = client.post(
            action_url(order.pk, "pickup"),
            {"payment_method": PaymentMethod.CASH, "received_amount": amount},
            format="json",
        )
        assert_unified_error(response, status=400)
        assert Order.objects.get(pk=order.pk).status == OrderStatus.CONFIRMED
        assert not PaymentRecord.objects.filter(order=order).exists()
        assert stock_of(setup.depot, setup.product).physical_quantity == 10

    @pytest.mark.parametrize("data", [{}, {"payment_method": ""}, {"payment_method": "CARD"}])
    def test_invalid_payment_method_is_400(self, client, setup, customer, data):
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED)
        response = client.post(action_url(order.pk, "pickup"), data, format="json")
        assert_unified_error(response, status=400)
        assert Order.objects.get(pk=order.pk).status == OrderStatus.CONFIRMED

    def test_pickup_pending_order_is_409(self, client, setup, customer):
        order = place_order(setup, customer)
        response = client.post(
            action_url(order.pk, "pickup"), {"payment_method": PaymentMethod.CASH}, format="json"
        )
        assert_unified_error(response, status=409, code="INVALID_ORDER_TRANSITION")

    def test_pickup_twice_is_409(self, client, setup, customer):
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED)
        data = {"payment_method": PaymentMethod.CASH}
        assert client.post(action_url(order.pk, "pickup"), data, format="json").status_code == 200
        response = client.post(action_url(order.pk, "pickup"), data, format="json")
        assert_unified_error(response, status=409, code="INVALID_ORDER_TRANSITION")
        assert movements(StockMovementType.PICKUP_OUT).count() == 1
        assert PaymentRecord.objects.filter(order=order).count() == 1

    def test_pickup_overdue_confirmed_is_no_show(self, auth_client, depot_manager, setup, customer):
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED)  # retrait limite 12:05
        with freeze_time("2026-03-04 12:30:00+01:00"):
            client = auth_client(depot_manager)
            response = client.post(
                action_url(order.pk, "pickup"), {"payment_method": PaymentMethod.CASH}, format="json"
            )
        assert_unified_error(response, status=409, code="ORDER_EXPIRED")
        order = Order.objects.get(pk=order.pk)
        assert order.status == OrderStatus.EXPIRED
        assert order.counted_as_no_show is True
        assert stock_of(setup.depot, setup.product).reserved_quantity == 0
        assert not PaymentRecord.objects.filter(order=order).exists()

    def test_pickup_foreign_order_is_404(self, client, other_customer):
        foreign = make_order_in_state(make_order_setup(), other_customer, OrderStatus.CONFIRMED)
        response = client.post(
            action_url(foreign.pk, "pickup"), {"payment_method": PaymentMethod.CASH}, format="json"
        )
        assert_unified_error(response, status=404, code="NOT_FOUND")
        assert Order.objects.get(pk=foreign.pk).status == OrderStatus.CONFIRMED

    def test_first_acquisition_pickup_creates_no_empty_stock(self, client, setup, customer):
        order = make_order_in_state(
            setup, customer, OrderStatus.CONFIRMED, operation_type=OperationType.FIRST_ACQUISITION
        )
        response = client.post(
            action_url(order.pk, "pickup"), {"payment_method": PaymentMethod.CASH}, format="json"
        )
        assert response.status_code == 200
        assert Decimal(str(response.json()["payment"]["expected_amount"])) == Decimal("8000")
        assert movements(StockMovementType.EMPTY_RETURN).count() == 0


# =========================================================================== #
# POST .../cancel-non-conformity/
# =========================================================================== #
class TestCancelNonConformity:
    URL_NAME = "cancel-non-conformity"

    def test_cancel(self, client, setup, customer):
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED, quantity=2)
        response = client.post(
            action_url(order.pk, self.URL_NAME), {"reason": "Bouteille abîmée"}, format="json"
        )
        assert response.status_code == 200
        assert_no_store(response)
        body = response.json()
        assert set(body) == DEPOT_ORDER_KEYS
        assert body["status"] == OrderStatus.CANCELLED
        assert body["cancellation_source"] == OrderCancellationSource.DEPOT_NON_CONFORMITY
        assert body["counted_as_no_show"] is False
        assert body["status_reason"] == "Bouteille abîmée"
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (10, 0)

    @pytest.mark.parametrize("data", [None, {}, {"reason": ""}, {"reason": "  "}])
    def test_reason_required(self, client, setup, customer, data):
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED)
        response = client.post(action_url(order.pk, self.URL_NAME), data, format="json")
        assert_unified_error(response, status=400)
        assert Order.objects.get(pk=order.pk).status == OrderStatus.CONFIRMED

    def test_pending_order_is_409(self, client, setup, customer):
        order = place_order(setup, customer)
        response = client.post(action_url(order.pk, self.URL_NAME), {"reason": "x"}, format="json")
        assert_unified_error(response, status=409, code="INVALID_ORDER_TRANSITION")

    @pytest.mark.parametrize(
        "state", [OrderStatus.PICKED_UP, OrderStatus.REFUSED, OrderStatus.CANCELLED, OrderStatus.EXPIRED]
    )
    def test_final_order_is_409(self, client, setup, customer, state):
        order = make_order_in_state(setup, customer, state)
        response = client.post(action_url(order.pk, self.URL_NAME), {"reason": "x"}, format="json")
        assert_unified_error(response, status=409, code="INVALID_ORDER_TRANSITION")
        assert Order.objects.get(pk=order.pk).status == state

    def test_foreign_order_is_404(self, client, other_customer):
        foreign = make_order_in_state(make_order_setup(), other_customer, OrderStatus.CONFIRMED)
        response = client.post(action_url(foreign.pk, self.URL_NAME), {"reason": "x"}, format="json")
        assert_unified_error(response, status=404, code="NOT_FOUND")