"""Vues API commandes client (/api/v1/orders/...) et dépôt (/api/v1/depot/orders/...)."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Brand, Product
from apps.core.api.mixins import NoStoreResponseMixin
from apps.core.api.serializers import ApiErrorSerializer
from apps.core.exceptions import NotFoundDomainError, ValidationDomainError
from apps.depots.api.permissions import IsDepotManagerWithDepot, get_request_managed_depot
from apps.depots.models import Depot
from apps.orders import selectors, services
from apps.orders.api.permissions import IsCustomer
from apps.orders.api.serializers import (
    CustomerOrderSerializer,
    DepotOrderSerializer,
    OrderCancelRequestSerializer,
    OrderCreateRequestSerializer,
    OrderFilterQuerySerializer,
    OrderPickupRequestSerializer,
    OrderReasonRequiredRequestSerializer,
)

# === Vues Client (/api/v1/orders/...) ===


class CustomerOrderListCreateView(NoStoreResponseMixin, ListAPIView):
    permission_classes = [IsCustomer]
    serializer_class = CustomerOrderSerializer

    def get_queryset(self):
        query = OrderFilterQuerySerializer(data=self.request.query_params.dict())
        query.is_valid(raise_exception=True)
        return selectors.list_customer_orders(
            customer=self.request.user,
            status=query.validated_data.get("status"),
        )

    @extend_schema(
        tags=["Customer Orders"],
        summary="Lister les commandes du client connecté",
        parameters=[OrderFilterQuerySerializer],
        responses={
            200: CustomerOrderSerializer(many=True),
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        tags=["Customer Orders"],
        summary="Créer une commande de retrait au dépôt avec réservation atomique du stock",
        request=OrderCreateRequestSerializer,
        responses={
            201: CustomerOrderSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
    )
    def post(self, request) -> Response:
        serializer = OrderCreateRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        depot = Depot.objects.filter(pk=data["depot_id"]).first()
        if depot is None:
            raise NotFoundDomainError("Dépôt introuvable.", code="NOT_FOUND")

        product = Product.objects.select_related("brand").filter(pk=data["product_id"]).first()
        if product is None:
            raise NotFoundDomainError("Produit introuvable.", code="NOT_FOUND")

        exchange_brand: Brand | None = None
        if data.get("exchange_brand_id") is not None:
            exchange_brand = Brand.objects.filter(pk=data["exchange_brand_id"]).first()
            if exchange_brand is None:
                raise ValidationDomainError(
                    "Marque de bouteille vide introuvable.",
                    details={"exchange_brand_id": ["Marque inconnue."]},
                )

        order = services.create_order(
            customer=request.user,
            depot=depot,
            product=product,
            operation_type=data["operation_type"],
            quantity=data["quantity"],
            exchange_brand=exchange_brand,
        )
        hydrated = selectors.get_customer_order(customer=request.user, order_id=order.pk)
        return Response(CustomerOrderSerializer(hydrated).data, status=status.HTTP_201_CREATED)


class CustomerOrderDetailView(NoStoreResponseMixin, APIView):
    permission_classes = [IsCustomer]

    @extend_schema(
        tags=["Customer Orders"],
        summary="Consulter le détail d'une de ses commandes",
        responses={
            200: CustomerOrderSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
        },
    )
    def get(self, request, order_id) -> Response:
        order = selectors.get_customer_order(customer=request.user, order_id=order_id)
        return Response(CustomerOrderSerializer(order).data, status=status.HTTP_200_OK)


class CustomerOrderCancelView(NoStoreResponseMixin, APIView):
    permission_classes = [IsCustomer]

    @extend_schema(
        tags=["Customer Orders"],
        summary="Annuler sa commande (EN_ATTENTE ou CONFIRMEE)",
        request=OrderCancelRequestSerializer,
        responses={
            200: CustomerOrderSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
    )
    def post(self, request, order_id) -> Response:
        order = selectors.get_customer_order(customer=request.user, order_id=order_id)
        serializer = OrderCancelRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = services.cancel_order_by_customer(
            order=order,
            customer=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        hydrated = selectors.get_customer_order(customer=request.user, order_id=updated.pk)
        return Response(CustomerOrderSerializer(hydrated).data, status=status.HTTP_200_OK)


# === Vues Responsable de dépôt (/api/v1/depot/orders/...) ===


class DepotOrderListView(NoStoreResponseMixin, ListAPIView):
    permission_classes = [IsDepotManagerWithDepot]
    serializer_class = DepotOrderSerializer

    def get_queryset(self):
        depot = get_request_managed_depot(self.request)
        query = OrderFilterQuerySerializer(data=self.request.query_params.dict())
        query.is_valid(raise_exception=True)
        return selectors.list_depot_orders(
            depot=depot,
            status=query.validated_data.get("status"),
        )

    @extend_schema(
        tags=["Depot Orders"],
        summary="Lister les commandes reçues par son dépôt",
        parameters=[OrderFilterQuerySerializer],
        responses={
            200: DepotOrderSerializer(many=True),
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class DepotOrderDetailView(NoStoreResponseMixin, APIView):
    permission_classes = [IsDepotManagerWithDepot]

    @extend_schema(
        tags=["Depot Orders"],
        summary="Consulter le détail d'une commande de son dépôt",
        responses={
            200: DepotOrderSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
        },
    )
    def get(self, request, order_id) -> Response:
        depot = get_request_managed_depot(request)
        order = selectors.get_depot_order(depot=depot, order_id=order_id)
        return Response(DepotOrderSerializer(order).data, status=status.HTTP_200_OK)


class DepotOrderAcceptView(NoStoreResponseMixin, APIView):
    permission_classes = [IsDepotManagerWithDepot]

    @extend_schema(
        tags=["Depot Orders"],
        summary="Accepter une commande EN_ATTENTE (calcule l'échéance de retrait)",
        request=None,
        responses={
            200: DepotOrderSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
    )
    def post(self, request, order_id) -> Response:
        depot = get_request_managed_depot(request)
        order = selectors.get_depot_order(depot=depot, order_id=order_id)
        updated = services.accept_order(order=order, actor=request.user, depot=depot)
        hydrated = selectors.get_depot_order(depot=depot, order_id=updated.pk)
        return Response(DepotOrderSerializer(hydrated).data, status=status.HTTP_200_OK)


class DepotOrderRefuseView(NoStoreResponseMixin, APIView):
    permission_classes = [IsDepotManagerWithDepot]

    @extend_schema(
        tags=["Depot Orders"],
        summary="Refuser une commande EN_ATTENTE avec motif obligatoire",
        request=OrderReasonRequiredRequestSerializer,
        responses={
            200: DepotOrderSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
    )
    def post(self, request, order_id) -> Response:
        depot = get_request_managed_depot(request)
        order = selectors.get_depot_order(depot=depot, order_id=order_id)
        serializer = OrderReasonRequiredRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = services.refuse_order(
            order=order,
            actor=request.user,
            reason=serializer.validated_data["reason"],
            depot=depot,
        )
        hydrated = selectors.get_depot_order(depot=depot, order_id=updated.pk)
        return Response(DepotOrderSerializer(hydrated).data, status=status.HTTP_200_OK)


class DepotOrderPickupView(NoStoreResponseMixin, APIView):
    permission_classes = [IsDepotManagerWithDepot]

    @extend_schema(
        tags=["Depot Orders"],
        summary="Valider le retrait au comptoir, le paiement et le retour bouteille vide",
        request=OrderPickupRequestSerializer,
        responses={
            200: DepotOrderSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
    )
    def post(self, request, order_id) -> Response:
        depot = get_request_managed_depot(request)
        order = selectors.get_depot_order(depot=depot, order_id=order_id)
        serializer = OrderPickupRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        updated = services.complete_pickup(
            order=order,
            actor=request.user,
            payment_method=data["payment_method"],
            received_amount=data.get("received_amount"),
            external_reference=data.get("external_reference", ""),
            notes=data.get("notes", ""),
            depot=depot,
        )
        hydrated = selectors.get_depot_order(depot=depot, order_id=updated.pk)
        return Response(DepotOrderSerializer(hydrated).data, status=status.HTTP_200_OK)


class DepotOrderCancelNonConformityView(NoStoreResponseMixin, APIView):
    permission_classes = [IsDepotManagerWithDepot]

    @extend_schema(
        tags=["Depot Orders"],
        summary="Annuler une commande CONFIRMEE pour bouteille vide non conforme",
        request=OrderReasonRequiredRequestSerializer,
        responses={
            200: DepotOrderSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
    )
    def post(self, request, order_id) -> Response:
        depot = get_request_managed_depot(request)
        order = selectors.get_depot_order(depot=depot, order_id=order_id)
        serializer = OrderReasonRequiredRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated = services.cancel_order_non_conformity(
            order=order,
            actor=request.user,
            reason=serializer.validated_data["reason"],
            depot=depot,
        )
        hydrated = selectors.get_depot_order(depot=depot, order_id=updated.pk)
        return Response(DepotOrderSerializer(hydrated).data, status=status.HTTP_200_OK)
