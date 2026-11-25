"""Jalon 3 / Lot 4 — sécurité des endpoints commandes.

Couvre : matrice rôles / anonyme / compte désactivé, IDOR cross-customer et cross-depot
(y compris dépôt suspendu), ``Cache-Control: no-store`` sur 2xx et 4xx, mass assignment,
payloads hostiles, méthodes HTTP interdites et confidentialité (jamais d'email / mot de passe).
"""
from decimal import Decimal

import pytest
from freezegun import freeze_time

from apps.accounts.models import User, UserRole
from apps.depots.models import DepotStatus, OperationType
from apps.orders.models import (
    Order,
    OrderCancellationSource,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from tests.factories_orders import (
    DEPOT_CUSTOMER_KEYS,
    FORBIDDEN_PRIVACY_KEYS,
    FROZEN_ISO,
    NONEXISTENT_ID,
    at,
    make_order_in_state,
    make_order_setup,
    place_order,
    stock_of,
    walk_keys,
)
from tests.helpers import assert_unified_error, create_user

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _frozen_clock():
    with freeze_time(FROZEN_ISO):
        yield


@pytest.fixture(autouse=True)
def _platform(platform_setting):
    return platform_setting


@pytest.fixture
def world(depot_manager, customer):
    """Un dépôt rattaché à ``depot_manager`` et une commande PENDING de ``customer``."""
    setup = make_order_setup(manager=depot_manager)
    order = place_order(setup, customer, quantity=2)
    return setup, order


# --------------------------------------------------------------------------- #
# Catalogue des endpoints : nom -> (méthode, url, corps)
# --------------------------------------------------------------------------- #
def endpoints(order_id):
    return {
        "customer_list": ("get", "/api/v1/orders/", None),
        "customer_create": ("post", "/api/v1/orders/", {}),
        "customer_detail": ("get", f"/api/v1/orders/{order_id}/", None),
        "customer_cancel": ("post", f"/api/v1/orders/{order_id}/cancel/", {}),
        "depot_list": ("get", "/api/v1/depot/orders/", None),
        "depot_detail": ("get", f"/api/v1/depot/orders/{order_id}/", None),
        "depot_accept": ("post", f"/api/v1/depot/orders/{order_id}/accept/", {}),
        "depot_refuse": ("post", f"/api/v1/depot/orders/{order_id}/refuse/", {"reason": "x"}),
        "depot_pickup": (
            "post",
            f"/api/v1/depot/orders/{order_id}/pickup/",
            {"payment_method": PaymentMethod.CASH},
        ),
        "depot_cancel_nc": (
            "post",
            f"/api/v1/depot/orders/{order_id}/cancel-non-conformity/",
            {"reason": "x"},
        ),
    }


ALL_NAMES = list(endpoints(NONEXISTENT_ID))
CUSTOMER_NAMES = [n for n in ALL_NAMES if n.startswith("customer_")]
DEPOT_NAMES = [n for n in ALL_NAMES if n.startswith("depot_")]
ID_NAMES = [n for n in ALL_NAMES if n not in {"customer_list", "customer_create", "depot_list"}]


def call(client, name, order_id):
    method, url, body = endpoints(order_id)[name]
    if method == "get":
        return client.get(url)
    return client.post(url, body, format="json")


def assert_no_store(response):
    assert "no-store" in response["Cache-Control"], response.status_code


# =========================================================================== #
# Matrice d'authentification et de rôles
# =========================================================================== #
class TestAuthMatrix:
    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_anonymous_is_401(self, api_client, world, name):
        _, order = world
        response = call(api_client, name, order.pk)
        assert_unified_error(response, status=401)
        assert_no_store(response)

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_deactivated_account_is_401(self, auth_client, world, customer, depot_manager, name):
        _, order = world
        user = customer if name.startswith("customer_") else depot_manager
        client = auth_client(user)  # session valide AVANT la désactivation
        User.objects.filter(pk=user.pk).update(is_active=False)
        response = call(client, name, order.pk)
        assert_unified_error(response, status=401)
        assert_no_store(response)

    @pytest.mark.parametrize("name", CUSTOMER_NAMES)
    @pytest.mark.parametrize("role_fixture", ["depot_manager", "admin_user"])
    def test_customer_endpoints_forbid_non_customers(
        self, request, auth_client, world, name, role_fixture
    ):
        _, order = world
        client = auth_client(request.getfixturevalue(role_fixture))
        response = call(client, name, order.pk)
        assert_unified_error(response, status=403)
        assert_no_store(response)

    @pytest.mark.parametrize("name", DEPOT_NAMES)
    @pytest.mark.parametrize("actor", ["customer", "admin_user", "manager_without_depot"])
    def test_depot_endpoints_forbid_other_roles(self, request, auth_client, world, name, actor):
        _, order = world
        if actor == "manager_without_depot":
            user = create_user(role=UserRole.DEPOT_MANAGER)  # aucun dépôt rattaché
        else:
            user = request.getfixturevalue(actor)
        response = call(auth_client(user), name, order.pk)
        assert_unified_error(response, status=403)
        assert_no_store(response)

    @pytest.mark.parametrize("name", DEPOT_NAMES)
    def test_forbidden_roles_cannot_mutate_state(self, auth_client, world, customer, name):
        setup, order = world
        call(auth_client(customer), name, order.pk)
        assert Order.objects.get(pk=order.pk).status == OrderStatus.PENDING
        assert stock_of(setup.depot, setup.product).reserved_quantity == 2


# =========================================================================== #
# IDOR : isolation cross-customer et cross-depot
# =========================================================================== #
class TestIdor:
    @pytest.mark.parametrize("name", ["customer_detail", "customer_cancel"])
    def test_other_customer_gets_404(self, auth_client, world, other_customer, name):
        setup, order = world
        response = call(auth_client(other_customer), name, order.pk)
        assert_unified_error(response, status=404, code="NOT_FOUND")
        assert_no_store(response)
        assert Order.objects.get(pk=order.pk).status == OrderStatus.PENDING
        assert stock_of(setup.depot, setup.product).reserved_quantity == 2

    def test_other_customer_list_does_not_leak(self, auth_client, world, other_customer):
        body = auth_client(other_customer).get("/api/v1/orders/").json()
        assert body["count"] == 0 and body["results"] == []

    @pytest.mark.parametrize("name", ["depot_detail", "depot_accept", "depot_refuse", "depot_cancel_nc"])
    @pytest.mark.parametrize("foreign_status", [DepotStatus.ACTIVE, DepotStatus.SUSPENDED])
    def test_other_depot_manager_gets_404(self, auth_client, world, name, foreign_status):
        setup, order = world
        intruder_setup = make_order_setup()
        intruder_setup.depot.status = foreign_status
        intruder_setup.depot.save(update_fields=["status"])

        response = call(auth_client(intruder_setup.manager), name, order.pk)

        assert_unified_error(response, status=404, code="NOT_FOUND")  # jamais 403 (pas d'oracle)
        assert_no_store(response)
        assert Order.objects.get(pk=order.pk).status == OrderStatus.PENDING

    @pytest.mark.parametrize("foreign_status", [DepotStatus.ACTIVE, DepotStatus.SUSPENDED])
    def test_other_depot_manager_cannot_pickup(self, auth_client, customer, foreign_status):
        victim_setup = make_order_setup()
        order = make_order_in_state(victim_setup, customer, OrderStatus.CONFIRMED)
        intruder_setup = make_order_setup()
        intruder_setup.depot.status = foreign_status
        intruder_setup.depot.save(update_fields=["status"])

        response = call(auth_client(intruder_setup.manager), "depot_pickup", order.pk)

        assert_unified_error(response, status=404, code="NOT_FOUND")
        assert Order.objects.get(pk=order.pk).status == OrderStatus.CONFIRMED
        assert stock_of(victim_setup.depot, victim_setup.product).physical_quantity == 10

    def test_other_depot_list_does_not_leak(self, auth_client, world):
        intruder_setup = make_order_setup()
        body = auth_client(intruder_setup.manager).get("/api/v1/depot/orders/").json()
        assert body["count"] == 0

    @pytest.mark.parametrize("name", ID_NAMES)
    def test_unknown_id_is_404(self, auth_client, depot_manager, customer, world, name):
        user = customer if name.startswith("customer_") else depot_manager
        assert_unified_error(
            call(auth_client(user), name, NONEXISTENT_ID), status=404, code="NOT_FOUND"
        )


# =========================================================================== #
# Cache-Control: no-store sur 2xx et 4xx
# =========================================================================== #
class TestNoStore:
    def test_success_and_error_responses(self, auth_client, world, customer, depot_manager, other_customer):
        setup, order = world
        cust, mgr = auth_client(customer), auth_client(depot_manager)
        responses = {
            200: [
                cust.get("/api/v1/orders/"),
                cust.get(f"/api/v1/orders/{order.pk}/"),
                mgr.get("/api/v1/depot/orders/"),
                mgr.get(f"/api/v1/depot/orders/{order.pk}/"),
                mgr.post(f"/api/v1/depot/orders/{order.pk}/accept/"),
            ],
            400: [mgr.post(f"/api/v1/depot/orders/{order.pk}/cancel-non-conformity/", {}, format="json")],
            401: [auth_client(customer).__class__().get("/api/v1/orders/")],
            403: [cust.get("/api/v1/depot/orders/")],
            404: [auth_client(other_customer).get(f"/api/v1/orders/{order.pk}/")],
            409: [mgr.post(f"/api/v1/depot/orders/{order.pk}/accept/")],
        }
        for expected, batch in responses.items():
            for response in batch:
                assert response.status_code == expected, (expected, response.status_code)
                assert_no_store(response)

    def test_created_201_is_no_store(self, auth_client, customer):
        setup = make_order_setup()
        response = auth_client(customer).post(
            "/api/v1/orders/",
            {
                "depot_id": setup.depot.pk,
                "product_id": setup.product.pk,
                "operation_type": OperationType.REFILL,
                "quantity": 1,
            },
            format="json",
        )
        assert response.status_code == 201
        assert_no_store(response)


# =========================================================================== #
# Mass assignment
# =========================================================================== #
INJECTED = {
    "customer": None,  # rempli dans les tests (id d'un autre client)
    "status": OrderStatus.PICKED_UP,
    "total_amount": 1,
    "payment_status": PaymentStatus.PAID,
    "depot_id": None,
    "cancellation_source": OrderCancellationSource.SYSTEM,
    "counted_as_no_show": True,
    "reference": "FAY-HACKED",
}


class TestMassAssignment:
    def injected(self, other_customer, other_depot):
        data = dict(INJECTED)
        data["customer"] = other_customer.pk
        data["depot_id"] = other_depot.pk
        return data

    def assert_untouched_identity(self, order, customer, setup, total="2000"):
        order = Order.objects.get(pk=order.pk)
        assert order.customer == customer
        assert order.depot == setup.depot
        assert order.total_amount == Decimal(total)
        assert order.reference != "FAY-HACKED"
        return order

    def test_customer_cancel(self, auth_client, world, customer, other_customer):
        setup, order = world
        data = self.injected(other_customer, make_order_setup().depot)
        data["reason"] = "ok"
        response = auth_client(customer).post(f"/api/v1/orders/{order.pk}/cancel/", data, format="json")
        assert response.status_code in (200, 400)
        order = self.assert_untouched_identity(order, customer, setup)
        if response.status_code == 200:
            assert order.status == OrderStatus.CANCELLED
            assert order.cancellation_source == OrderCancellationSource.CUSTOMER
            assert order.counted_as_no_show is False
            assert order.payment_status == PaymentStatus.PENDING

    def test_depot_accept(self, auth_client, world, customer, depot_manager, other_customer):
        setup, order = world
        data = self.injected(other_customer, make_order_setup().depot)
        response = auth_client(depot_manager).post(
            f"/api/v1/depot/orders/{order.pk}/accept/", data, format="json"
        )
        assert response.status_code in (200, 400)
        order = self.assert_untouched_identity(order, customer, setup)
        if response.status_code == 200:
            assert order.status == OrderStatus.CONFIRMED
            assert order.payment_status == PaymentStatus.PENDING
            assert order.counted_as_no_show is False

    def test_depot_refuse(self, auth_client, world, customer, depot_manager, other_customer):
        setup, order = world
        data = self.injected(other_customer, make_order_setup().depot)
        data["reason"] = "Rupture"
        response = auth_client(depot_manager).post(
            f"/api/v1/depot/orders/{order.pk}/refuse/", data, format="json"
        )
        assert response.status_code in (200, 400)
        order = self.assert_untouched_identity(order, customer, setup)
        if response.status_code == 200:
            assert order.status == OrderStatus.REFUSED
            assert order.status_reason == "Rupture"
            assert order.counted_as_no_show is False
            assert order.payment_status == PaymentStatus.PENDING

    def test_depot_pickup(self, auth_client, customer, depot_manager, other_customer):
        setup = make_order_setup(manager=depot_manager)
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED, quantity=2)
        data = self.injected(other_customer, make_order_setup().depot)
        data.update(payment_method=PaymentMethod.CASH, status=OrderStatus.REFUSED)
        response = auth_client(depot_manager).post(
            f"/api/v1/depot/orders/{order.pk}/pickup/", data, format="json"
        )
        assert response.status_code in (200, 400)
        order = self.assert_untouched_identity(order, customer, setup)
        if response.status_code == 200:
            assert order.status == OrderStatus.PICKED_UP
            assert order.payment_status == PaymentStatus.PAID
            assert order.counted_as_no_show is False

    def test_depot_cancel_non_conformity(self, auth_client, customer, depot_manager, other_customer):
        setup = make_order_setup(manager=depot_manager)
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED, quantity=2)
        data = self.injected(other_customer, make_order_setup().depot)
        data["reason"] = "Non conforme"
        response = auth_client(depot_manager).post(
            f"/api/v1/depot/orders/{order.pk}/cancel-non-conformity/", data, format="json"
        )
        assert response.status_code in (200, 400)
        order = self.assert_untouched_identity(order, customer, setup)
        if response.status_code == 200:
            assert order.status == OrderStatus.CANCELLED
            assert order.cancellation_source == OrderCancellationSource.DEPOT_NON_CONFORMITY
            assert order.counted_as_no_show is False

    def test_customer_create_cannot_target_other_customer(self, auth_client, customer, other_customer):
        setup = make_order_setup()
        data = {
            "depot_id": setup.depot.pk,
            "product_id": setup.product.pk,
            "operation_type": OperationType.REFILL,
            "quantity": 1,
            "customer": other_customer.pk,
            "customer_id": other_customer.pk,
            "status": OrderStatus.CONFIRMED,
            "total_amount": 1,
            "payment_status": PaymentStatus.PAID,
        }
        response = auth_client(customer).post("/api/v1/orders/", data, format="json")
        assert response.status_code in (201, 400)
        assert not Order.objects.filter(customer=other_customer).exists()
        for order in Order.objects.all():
            assert order.customer == customer
            assert order.status == OrderStatus.PENDING
            assert order.payment_status == PaymentStatus.PENDING
            assert order.total_amount == Decimal("1000")


# =========================================================================== #
# Payloads hostiles
# =========================================================================== #
class TestHostilePayloads:
    @pytest.fixture
    def setup_customer_client(self, auth_client, customer):
        setup = make_order_setup()
        return setup, auth_client(customer)

    @pytest.mark.parametrize(
        "raw", ["{bad json", "", "null", "[]", '"text"', "42"], ids=["broken", "empty", "null", "list", "str", "int"]
    )
    def test_non_object_bodies_on_create_are_400(self, setup_customer_client, raw):
        _, client = setup_customer_client
        response = client.post("/api/v1/orders/", raw, content_type="application/json")
        assert_unified_error(response, status=400)
        assert_no_store(response)
        assert Order.objects.count() == 0

    @pytest.mark.parametrize(
        "field,value",
        [
            ("depot_id", "1 OR 1=1"),
            ("depot_id", {"$ne": 1}),
            ("depot_id", [1, 2]),
            ("product_id", "'; DROP TABLE orders_order; --"),
            ("product_id", {"$gt": ""}),
            ("operation_type", "REFILL' OR '1'='1"),
            ("operation_type", ["REFILL"]),
            ("exchange_brand_id", "x"),
        ],
    )
    def test_hostile_values_never_500_nor_create(self, setup_customer_client, field, value):
        setup, client = setup_customer_client
        data = {
            "depot_id": setup.depot.pk,
            "product_id": setup.product.pk,
            "operation_type": OperationType.REFILL,
            "quantity": 1,
        }
        data[field] = value
        response = client.post("/api/v1/orders/", data, format="json")
        assert response.status_code in (400, 404)
        assert_no_store(response)
        assert Order.objects.count() == 0

    @pytest.mark.parametrize("reason", ["'; DROP TABLE orders_order; --", "<script>alert(1)</script>", "é😀 日本語"])
    def test_hostile_reason_is_stored_verbatim_not_interpreted(
        self, auth_client, world, depot_manager, reason
    ):
        _, order = world
        response = auth_client(depot_manager).post(
            f"/api/v1/depot/orders/{order.pk}/refuse/", {"reason": reason}, format="json"
        )
        assert response.status_code == 200
        assert Order.objects.get(pk=order.pk).status_reason == reason
        assert Order.objects.filter(pk=order.pk).exists()

    def test_nul_byte_in_reason_never_causes_server_error(self, auth_client, world, depot_manager):
        _, order = world
        response = auth_client(depot_manager).post(
            f"/api/v1/depot/orders/{order.pk}/refuse/", {"reason": "abc\x00def"}, format="json"
        )
        assert response.status_code < 500
        assert_no_store(response)

    @pytest.mark.parametrize("amount", ["NaN", "Infinity", "-1", "1e999", {}, [], True, "0x10"])
    def test_hostile_received_amount_is_rejected(self, auth_client, customer, depot_manager, amount):
        setup = make_order_setup(manager=depot_manager)
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED)
        response = auth_client(depot_manager).post(
            f"/api/v1/depot/orders/{order.pk}/pickup/",
            {"payment_method": PaymentMethod.CASH, "received_amount": amount},
            format="json",
        )
        assert response.status_code == 400
        assert Order.objects.get(pk=order.pk).status == OrderStatus.CONFIRMED

    @pytest.mark.parametrize("raw", ["{bad", "[]", "null"])
    def test_non_object_bodies_on_depot_actions_are_400(self, auth_client, world, depot_manager, raw):
        _, order = world
        response = auth_client(depot_manager).post(
            f"/api/v1/depot/orders/{order.pk}/refuse/", raw, content_type="application/json"
        )
        assert_unified_error(response, status=400)
        assert Order.objects.get(pk=order.pk).status == OrderStatus.PENDING


# =========================================================================== #
# Méthodes HTTP interdites
# =========================================================================== #
class TestForbiddenMethods:
    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    @pytest.mark.parametrize("name", ["customer_list", "customer_detail", "customer_cancel"])
    def test_customer_endpoints(self, auth_client, world, customer, name, method):
        _, order = world
        _, url, _ = endpoints(order.pk)[name]
        response = getattr(auth_client(customer), method)(url, {}, format="json")
        assert response.status_code == 405
        assert Order.objects.filter(pk=order.pk).exists()

    @pytest.mark.parametrize("method", ["put", "patch", "delete"])
    @pytest.mark.parametrize("name", DEPOT_NAMES)
    def test_depot_endpoints(self, auth_client, world, depot_manager, name, method):
        _, order = world
        _, url, _ = endpoints(order.pk)[name]
        response = getattr(auth_client(depot_manager), method)(url, {}, format="json")
        assert response.status_code == 405
        assert Order.objects.get(pk=order.pk).status == OrderStatus.PENDING

    @pytest.mark.parametrize("suffix", ["cancel", "cancel-non-conformity", "accept", "refuse", "pickup"])
    def test_get_on_action_endpoints_is_405(self, auth_client, world, customer, depot_manager, suffix):
        _, order = world
        if suffix == "cancel":
            response = auth_client(customer).get(f"/api/v1/orders/{order.pk}/{suffix}/")
        else:
            response = auth_client(depot_manager).get(f"/api/v1/depot/orders/{order.pk}/{suffix}/")
        assert response.status_code == 405

    def test_post_on_detail_and_depot_list_is_405(self, auth_client, world, customer, depot_manager):
        _, order = world
        assert auth_client(customer).post(f"/api/v1/orders/{order.pk}/", {}, format="json").status_code == 405
        assert auth_client(depot_manager).post("/api/v1/depot/orders/", {}, format="json").status_code == 405
        assert (
            auth_client(depot_manager)
            .post(f"/api/v1/depot/orders/{order.pk}/", {}, format="json")
            .status_code
            == 405
        )


# =========================================================================== #
# Confidentialité
# =========================================================================== #
class TestPrivacy:
    def test_depot_order_exposes_only_name_and_phone(self, auth_client, world, customer, depot_manager):
        _, order = world
        response = auth_client(depot_manager).get(f"/api/v1/depot/orders/{order.pk}/")
        body = response.json()
        assert set(body["customer"]) == DEPOT_CUSTOMER_KEYS
        assert not (set(walk_keys(body)) & FORBIDDEN_PRIVACY_KEYS)
        assert customer.email not in response.content.decode()

    def test_depot_list_and_actions_never_leak_customer_secrets(
        self, auth_client, customer, depot_manager
    ):
        setup = make_order_setup(manager=depot_manager)
        order = make_order_in_state(setup, customer, OrderStatus.CONFIRMED)
        client = auth_client(depot_manager)
        responses = [
            client.get("/api/v1/depot/orders/"),
            client.get(f"/api/v1/depot/orders/{order.pk}/"),
            client.post(
                f"/api/v1/depot/orders/{order.pk}/pickup/",
                {"payment_method": PaymentMethod.CASH},
                format="json",
            ),
        ]
        for response in responses:
            assert response.status_code == 200
            text = response.content.decode()
            assert customer.email not in text
            assert not (set(walk_keys(response.json())) & FORBIDDEN_PRIVACY_KEYS)

    def test_status_history_never_exposes_emails_or_passwords(
        self, auth_client, world, customer, depot_manager
    ):
        setup, order = world
        mgr = auth_client(depot_manager)
        mgr.post(f"/api/v1/depot/orders/{order.pk}/accept/")
        body = mgr.get(f"/api/v1/depot/orders/{order.pk}/").json()
        customer_view = auth_client(customer).get(f"/api/v1/orders/{order.pk}/")
        for payload in (body, customer_view.json()):
            history = payload["status_history"]
            assert len(history) == 2
            assert not (set(walk_keys(history)) & FORBIDDEN_PRIVACY_KEYS)
            serialized = str(history)
            assert customer.email not in serialized
            assert depot_manager.email not in serialized
            assert "password" not in serialized.lower()

    def test_customer_view_never_exposes_manager_email(self, auth_client, world, customer, depot_manager):
        _, order = world
        response = auth_client(customer).get(f"/api/v1/orders/{order.pk}/")
        assert depot_manager.email not in response.content.decode()
        assert "password" not in response.content.decode().lower()