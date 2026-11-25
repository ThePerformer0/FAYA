"""Jalon 3 / Lot 4 — API client ``/api/v1/orders/...``.

L'horloge est figée à 10:00 (Africa/Douala) pour toute la durée de chaque test ;
les commandes « d'avant » sont fabriquées via les services avec un ``now=`` explicite.
Format d'erreur plat : ``{"code", "message", "details"}``.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils.dateparse import parse_datetime
from freezegun import freeze_time

from apps.depots.models import OperationType
from apps.inventory.models import StockMovementType, StockReservation, StockReservationStatus
from apps.orders import services as order_services
from apps.orders.models import (
    Order,
    OrderCancellationSource,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from tests.factories_orders import (
    BASE_NOW,
    CUSTOMER_ORDER_KEYS,
    FROZEN_ISO,
    NONEXISTENT_ID,
    ORDER_ITEM_KEYS,
    PAYMENT_KEYS,
    at,
    make_cancelled_orders,
    make_order_in_state,
    make_order_setup,
    make_suspension,
    movements,
    place_order,
    stock_of,
)
from tests.helpers import assert_unified_error

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/orders/"


def detail_url(order_id):
    return f"/api/v1/orders/{order_id}/"


def cancel_url(order_id):
    return f"/api/v1/orders/{order_id}/cancel/"


@pytest.fixture(autouse=True)
def _frozen_clock():
    with freeze_time(FROZEN_ISO):
        yield


@pytest.fixture(autouse=True)
def _platform(platform_setting):
    return platform_setting


@pytest.fixture
def setup():
    return make_order_setup()


@pytest.fixture
def client(auth_client, customer):
    return auth_client(customer)


def payload(setup, **overrides):
    data = {
        "depot_id": setup.depot.pk,
        "product_id": setup.product.pk,
        "operation_type": OperationType.REFILL,
        "quantity": 1,
    }
    data.update(overrides)
    return data


def assert_no_store(response):
    assert "no-store" in response["Cache-Control"]


# =========================================================================== #
# GET /api/v1/orders/
# =========================================================================== #
class TestListOrders:
    def test_empty_list_is_paginated(self, client):
        response = client.get(LIST_URL)
        assert response.status_code == 200
        assert_no_store(response)
        body = response.json()
        assert set(body) == {"count", "next", "previous", "results"}
        assert body["count"] == 0 and body["results"] == []

    def test_only_own_orders(self, client, setup, customer, other_customer):
        mine = make_cancelled_orders(setup, customer, 2)
        theirs = place_order(setup, other_customer)

        body = client.get(LIST_URL).json()

        assert body["count"] == 2
        assert {r["id"] for r in body["results"]} == {str(o.pk) for o in mine}
        assert str(theirs.pk) not in {str(r["id"]) for r in body["results"]}

    def test_result_keys_are_exact(self, client, setup, customer):
        place_order(setup, customer)
        result = client.get(LIST_URL).json()["results"][0]
        assert set(result) == CUSTOMER_ORDER_KEYS
        assert set(result["items"][0]) == ORDER_ITEM_KEYS
        assert result["payment"] is None

    def test_pagination_page_size_is_20(self, client, setup, customer):
        make_cancelled_orders(setup, customer, 21)
        body = client.get(LIST_URL).json()
        assert body["count"] == 21
        assert len(body["results"]) == 20
        assert body["next"] is not None and body["previous"] is None
        page2 = client.get(LIST_URL, {"page": 2}).json()
        assert len(page2["results"]) == 1 and page2["next"] is None

    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (OrderStatus.PENDING, 1),
            (OrderStatus.CANCELLED, 2),
            (OrderStatus.REFUSED, 1),
            (OrderStatus.CONFIRMED, 0),
            (OrderStatus.PICKED_UP, 0),
            (OrderStatus.EXPIRED, 0),
        ],
    )
    def test_status_filter(self, client, setup, customer, status, expected):
        make_cancelled_orders(setup, customer, 2)
        make_order_in_state(setup, customer, OrderStatus.REFUSED)
        place_order(setup, customer, now=at(11, 0))

        body = client.get(LIST_URL, {"status": status}).json()

        assert body["count"] == expected
        assert all(r["status"] == status for r in body["results"])

    @pytest.mark.parametrize("value", ["", "NOPE", "pending", "PENDING,CANCELLED"])
    def test_invalid_status_filter_is_400(self, client, value):
        response = client.get(LIST_URL, {"status": value})
        assert_unified_error(response, status=400)
        assert_no_store(response)

    def test_no_n_plus_one(self, client, setup, customer):
        make_cancelled_orders(setup, customer, 2)
        with CaptureQueriesContext(connection) as small:
            assert client.get(LIST_URL).status_code == 200
        make_cancelled_orders(setup, customer, 4)
        with CaptureQueriesContext(connection) as large:
            response = client.get(LIST_URL)
        assert response.json()["count"] == 6
        assert len(large) == len(small)


# =========================================================================== #
# POST /api/v1/orders/
# =========================================================================== #
class TestCreateOrder:
    def test_refill_created(self, client, setup, customer):
        response = client.post(LIST_URL, payload(setup, quantity=2), format="json")

        assert response.status_code == 201
        assert_no_store(response)
        body = response.json()
        assert set(body) == CUSTOMER_ORDER_KEYS
        assert body["status"] == OrderStatus.PENDING
        assert body["payment_status"] == PaymentStatus.PENDING
        assert body["payment"] is None
        assert body["pickup_deadline_at"] is None
        assert body["counted_as_no_show"] is False
        assert Decimal(str(body["total_amount"])) == Decimal("2000")
        assert parse_datetime(body["response_deadline_at"]) == BASE_NOW + timedelta(minutes=15)

        assert len(body["items"]) == 1
        item = body["items"][0]
        assert set(item) == ORDER_ITEM_KEYS
        assert str(item["product_id"]) == str(setup.product.pk)
        assert item["brand_name"] == setup.product.brand.name
        assert item["product_name"] == setup.product.name
        assert Decimal(str(item["capacity_kg"])) == setup.product.capacity_kg
        assert item["operation_type"] == OperationType.REFILL
        assert item["exchange_brand_name"] is None
        assert item["quantity"] == 2
        assert Decimal(str(item["unit_gas_price"])) == Decimal("1000")
        assert Decimal(str(item["unit_bottle_price"])) == 0
        assert Decimal(str(item["unit_deposit_amount"])) == 0
        assert Decimal(str(item["unit_total_price"])) == Decimal("1000")
        assert Decimal(str(item["line_total_amount"])) == Decimal("2000")

        assert len(body["status_history"]) == 1
        order = Order.objects.get(pk=body["id"])
        assert order.customer == customer
        assert stock_of(setup.depot, setup.product).reserved_quantity == 2

    def test_exchange_created(self, client, setup):
        response = client.post(
            LIST_URL,
            payload(
                setup,
                operation_type=OperationType.EXCHANGE,
                exchange_brand_id=setup.exchange_brand.pk,
            ),
            format="json",
        )
        assert response.status_code == 201
        item = response.json()["items"][0]
        assert item["exchange_brand_name"] == setup.exchange_brand.name
        assert Decimal(str(item["unit_total_price"])) == Decimal("1500")

    def test_first_acquisition_created(self, client, setup):
        response = client.post(
            LIST_URL,
            payload(setup, operation_type=OperationType.FIRST_ACQUISITION, quantity=2),
            format="json",
        )
        assert response.status_code == 201
        body = response.json()
        assert Decimal(str(body["total_amount"])) == Decimal("16000")
        item = body["items"][0]
        assert Decimal(str(item["unit_bottle_price"])) == Decimal("5000")
        assert Decimal(str(item["unit_deposit_amount"])) == Decimal("2000")

    @pytest.mark.parametrize("quantity", [True, False, "2", "abc", 0, -1, 4, 1.5, None, [1], {"a": 1}])
    def test_invalid_quantity_is_400(self, client, setup, quantity):
        response = client.post(LIST_URL, payload(setup, quantity=quantity), format="json")
        assert_unified_error(response, status=400)
        assert Order.objects.count() == 0

    @pytest.mark.parametrize("missing", ["depot_id", "product_id", "operation_type", "quantity"])
    def test_missing_field_is_400(self, client, setup, missing):
        data = payload(setup)
        data.pop(missing)
        assert_unified_error(client.post(LIST_URL, data, format="json"), status=400)
        assert Order.objects.count() == 0

    def test_unknown_operation_type_is_400(self, client, setup):
        response = client.post(LIST_URL, payload(setup, operation_type="TELEPORT"), format="json")
        assert_unified_error(response, status=400)

    def test_exchange_without_brand_is_400(self, client, setup):
        response = client.post(
            LIST_URL, payload(setup, operation_type=OperationType.EXCHANGE), format="json"
        )
        assert_unified_error(response, status=400)
        assert Order.objects.count() == 0

    def test_brand_forbidden_for_refill_is_400(self, client, setup):
        response = client.post(
            LIST_URL, payload(setup, exchange_brand_id=setup.exchange_brand.pk), format="json"
        )
        assert_unified_error(response, status=400)

    def test_product_without_offer_is_400(self, client, setup):
        from tests.factories_catalog import make_product

        response = client.post(
            LIST_URL, payload(setup, product_id=make_product().pk), format="json"
        )
        assert_unified_error(response, status=400)

    def test_second_active_order_is_409(self, client, setup):
        assert client.post(LIST_URL, payload(setup), format="json").status_code == 201
        response = client.post(LIST_URL, payload(setup), format="json")
        assert_unified_error(response, status=409, code="ACTIVE_ORDER_EXISTS")
        assert_no_store(response)
        assert Order.objects.count() == 1

    def test_insufficient_stock_is_409_and_atomic(self, client, customer):
        setup = make_order_setup(physical=1)
        response = client.post(LIST_URL, payload(setup, quantity=2), format="json")
        assert_unified_error(response, status=409, code="INSUFFICIENT_STOCK")
        assert Order.objects.count() == 0
        assert StockReservation.objects.count() == 0
        assert movements(StockMovementType.RESERVATION).count() == 0

    def test_suspended_customer_is_403(self, client, setup, customer):
        make_suspension(
            customer,
            starts_at=BASE_NOW - timedelta(days=1),
            ends_at=BASE_NOW + timedelta(days=2),
        )
        body = assert_unified_error(
            client.post(LIST_URL, payload(setup), format="json"),
            status=403,
            code="CUSTOMER_SUSPENDED",
        )
        assert "ends_at" in body["details"]

    @pytest.mark.parametrize(
        ("when", "code"),
        [
            ("2026-03-04 21:00:00+01:00", "DEPOT_CLOSED"),
            ("2026-03-04 19:45:00+01:00", "ORDER_CUTOFF_REACHED"),
        ],
    )
    def test_closed_or_cutoff_is_409(self, auth_client, customer, setup, when, code):
        with freeze_time(when):
            client = auth_client(customer)  # jeton émis à l'heure simulée
            response = client.post(LIST_URL, payload(setup), format="json")
        assert_unified_error(response, status=409, code=code)

    def test_mass_assignment_fields_are_ignored_or_rejected(
        self, client, setup, customer, other_customer
    ):
        hostile = payload(
            setup,
            customer=other_customer.pk,
            customer_id=other_customer.pk,
            status=OrderStatus.CONFIRMED,
            total_amount=1,
            payment_status=PaymentStatus.PAID,
            reference="FAY-HACKED",
            pickup_deadline_at="2030-01-01T00:00:00Z",
        )
        response = client.post(LIST_URL, hostile, format="json")
        assert response.status_code in (201, 400)
        if response.status_code == 201:
            order = Order.objects.get(pk=response.json()["id"])
            assert order.customer == customer
            assert order.status == OrderStatus.PENDING
            assert order.payment_status == PaymentStatus.PENDING
            assert order.total_amount == Decimal("1000")
            assert order.reference != "FAY-HACKED"
            assert order.pickup_deadline_at is None
        else:
            assert Order.objects.count() == 0
        assert not Order.objects.filter(customer=other_customer).exists()


# =========================================================================== #
# GET /api/v1/orders/{id}/
# =========================================================================== #
class TestRetrieveOrder:
    def test_own_order(self, client, setup, customer):
        order = place_order(setup, customer, quantity=2)
        response = client.get(detail_url(order.pk))
        assert response.status_code == 200
        assert_no_store(response)
        body = response.json()
        assert set(body) == CUSTOMER_ORDER_KEYS
        assert str(body["id"]) == str(order.pk)
        assert body["reference"] == order.reference

    def test_other_customer_order_is_404(self, client, setup, other_customer):
        order = place_order(setup, other_customer)
        response = client.get(detail_url(order.pk))
        assert_unified_error(response, status=404, code="NOT_FOUND")
        assert_no_store(response)

    def test_unknown_order_is_404(self, client):
        assert_unified_error(client.get(detail_url(NONEXISTENT_ID)), status=404, code="NOT_FOUND")

    def test_payment_and_history_after_pickup(self, client, setup, customer):
        order = place_order(setup, customer, quantity=2, now=at(9, 50))
        order_services.accept_order(order=order, actor=setup.manager, now=at(9, 55))
        order_services.complete_pickup(
            order=order,
            actor=setup.manager,
            payment_method=PaymentMethod.MOBILE_MONEY,
            external_reference="MM-42",
            notes="RAS",
            now=at(10, 0),
        )
        body = client.get(detail_url(order.pk)).json()

        assert body["status"] == OrderStatus.PICKED_UP
        assert body["payment_status"] == PaymentStatus.PAID
        assert body["picked_up_at"] is not None
        assert set(body["payment"]) == PAYMENT_KEYS
        payment = body["payment"]
        assert payment["payment_method"] == PaymentMethod.MOBILE_MONEY
        assert payment["status"] == PaymentStatus.PAID
        assert payment["external_reference"] == "MM-42"
        assert payment["notes"] == "RAS"
        assert Decimal(str(payment["expected_amount"])) == Decimal("2000")
        assert Decimal(str(payment["received_amount"])) == Decimal("2000")
        assert [h["to_status"] for h in body["status_history"]] == [
            OrderStatus.PENDING,
            OrderStatus.CONFIRMED,
            OrderStatus.PICKED_UP,
        ]


# =========================================================================== #
# POST /api/v1/orders/{id}/cancel/
# =========================================================================== #
class TestCancelOrder:
    @pytest.mark.parametrize("state", [OrderStatus.PENDING, OrderStatus.CONFIRMED])
    def test_cancel_with_reason(self, client, setup, customer, state):
        order = make_order_in_state(setup, customer, state, quantity=2)
        response = client.post(cancel_url(order.pk), {"reason": "Changement de plan"}, format="json")

        assert response.status_code == 200
        assert_no_store(response)
        body = response.json()
        assert set(body) == CUSTOMER_ORDER_KEYS
        assert body["status"] == OrderStatus.CANCELLED
        assert body["cancellation_source"] == OrderCancellationSource.CUSTOMER
        assert body["counted_as_no_show"] is False
        assert body["status_reason"] == "Changement de plan"
        assert body["cancelled_at"] is not None
        assert body["status_history"][-1]["to_status"] == OrderStatus.CANCELLED
        stock = stock_of(setup.depot, setup.product)
        assert (stock.physical_quantity, stock.reserved_quantity) == (10, 0)
        assert (
            StockReservation.objects.get(order=order).status == StockReservationStatus.RELEASED
        )

    def test_cancel_without_body(self, client, setup, customer):
        order = place_order(setup, customer)
        response = client.post(cancel_url(order.pk))
        assert response.status_code == 200
        assert response.json()["status"] == OrderStatus.CANCELLED

    @pytest.mark.parametrize(
        "state", [OrderStatus.REFUSED, OrderStatus.CANCELLED, OrderStatus.PICKED_UP, OrderStatus.EXPIRED]
    )
    def test_cancel_final_order_is_409(self, client, setup, customer, state):
        order = make_order_in_state(setup, customer, state)
        response = client.post(cancel_url(order.pk), {}, format="json")
        assert_unified_error(response, status=409, code="INVALID_ORDER_TRANSITION")
        assert_no_store(response)
        assert Order.objects.get(pk=order.pk).status == state

    def test_cancel_overdue_pending_is_409_and_persists_expiration(self, client, setup, customer):
        order = place_order(setup, customer, now=at(9, 40))  # échéance 09:55 < 10:00 figé
        response = client.post(cancel_url(order.pk), {}, format="json")
        assert_unified_error(response, status=409, code="ORDER_EXPIRED")
        order = Order.objects.get(pk=order.pk)
        assert order.status == OrderStatus.EXPIRED
        assert order.counted_as_no_show is False
        assert stock_of(setup.depot, setup.product).reserved_quantity == 0

    def test_other_customer_cannot_cancel(self, client, setup, other_customer):
        order = place_order(setup, other_customer)
        response = client.post(cancel_url(order.pk), {}, format="json")
        assert_unified_error(response, status=404, code="NOT_FOUND")
        assert Order.objects.get(pk=order.pk).status == OrderStatus.PENDING
        assert stock_of(setup.depot, setup.product).reserved_quantity == 1

    def test_unknown_order_is_404(self, client):
        assert_unified_error(
            client.post(cancel_url(NONEXISTENT_ID), {}, format="json"), status=404, code="NOT_FOUND"
        )

    def test_cancel_ignores_injected_state_fields(self, client, setup, customer):
        order = place_order(setup, customer)
        response = client.post(
            cancel_url(order.pk),
            {
                "reason": "ok",
                "status": OrderStatus.CONFIRMED,
                "cancellation_source": OrderCancellationSource.SYSTEM,
                "counted_as_no_show": True,
                "payment_status": PaymentStatus.PAID,
                "total_amount": 1,
            },
            format="json",
        )
        assert response.status_code in (200, 400)
        order = Order.objects.get(pk=order.pk)
        if response.status_code == 200:
            assert order.status == OrderStatus.CANCELLED
            assert order.cancellation_source == OrderCancellationSource.CUSTOMER
            assert order.counted_as_no_show is False
            assert order.payment_status == PaymentStatus.PENDING
            assert order.total_amount == Decimal("1000")
        else:
            assert order.status == OrderStatus.PENDING