"""Vues API privées de gestion des stocks et mouvements du dépôt (/api/v1/depot/stocks/...)."""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.models import Product
from apps.core.api.mixins import NoStoreResponseMixin
from apps.core.api.serializers import ApiErrorSerializer
from apps.core.exceptions import NotFoundDomainError
from apps.depots.api.permissions import IsDepotManagerWithDepot, get_request_managed_depot
from apps.inventory import selectors, services
from apps.inventory.api.serializers import (
    DepotStockSerializer,
    StockAdjustRequestSerializer,
    StockFilterQuerySerializer,
    StockMovementFilterQuerySerializer,
    StockMovementSerializer,
    StockMutationResponseSerializer,
    StockRestockRequestSerializer,
    StockScrapRequestSerializer,
)
from apps.inventory.models import StockMovementType


def _fetch_product_or_404(product_id) -> Product:
    product = Product.objects.select_related("brand").filter(pk=product_id).first()
    if product is None:
        raise NotFoundDomainError("Produit introuvable.", code="NOT_FOUND")
    return product


class ManagedStockListView(NoStoreResponseMixin, ListAPIView):
    permission_classes = [IsDepotManagerWithDepot]
    serializer_class = DepotStockSerializer

    def get_queryset(self):
        depot = get_request_managed_depot(self.request)
        query = StockFilterQuerySerializer(data=self.request.query_params.dict())
        query.is_valid(raise_exception=True)
        params = query.validated_data
        return selectors.list_depot_stocks(
            depot=depot,
            product_id=params.get("product"),
            category=params.get("category"),
        )

    @extend_schema(
        tags=["Depot Inventory"],
        summary="Consulter les stocks du dépôt par produit et catégorie",
        parameters=[StockFilterQuerySerializer],
        responses={
            200: DepotStockSerializer(many=True),
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ManagedStockRestockView(NoStoreResponseMixin, APIView):
    permission_classes = [IsDepotManagerWithDepot]

    @extend_schema(
        tags=["Depot Inventory"],
        summary="Approvisionner le stock physique d'un produit",
        request=StockRestockRequestSerializer,
        responses={
            200: StockMutationResponseSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
        },
    )
    def post(self, request) -> Response:
        depot = get_request_managed_depot(request)
        serializer = StockRestockRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        product = _fetch_product_or_404(data["product_id"])

        stock, movement = services.restock_depot_stock(
            depot=depot,
            product=product,
            category=data["category"],
            quantity=data["quantity"],
            actor=request.user,
            reason=data.get("reason", ""),
        )
        payload = StockMutationResponseSerializer({"stock": stock, "movement": movement}).data
        return Response(payload, status=status.HTTP_200_OK)


class ManagedStockAdjustView(NoStoreResponseMixin, APIView):
    permission_classes = [IsDepotManagerWithDepot]

    @extend_schema(
        tags=["Depot Inventory"],
        summary="Corriger manuellement un stock (inventaire / ajustement avec motif obligatoire)",
        request=StockAdjustRequestSerializer,
        responses={
            200: StockMutationResponseSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
    )
    def post(self, request) -> Response:
        depot = get_request_managed_depot(request)
        serializer = StockAdjustRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        product = _fetch_product_or_404(data["product_id"])

        stock, movement = services.adjust_depot_stock(
            depot=depot,
            product=product,
            category=data["category"],
            new_physical_quantity=data["new_physical_quantity"],
            actor=request.user,
            reason=data["reason"],
            movement_type=data.get("movement_type", StockMovementType.INVENTORY_CORRECTION),
            expected_physical_quantity=data.get("expected_physical_quantity"),
        )
        payload = StockMutationResponseSerializer({"stock": stock, "movement": movement}).data
        return Response(payload, status=status.HTTP_200_OK)


class ManagedStockScrapView(NoStoreResponseMixin, APIView):
    permission_classes = [IsDepotManagerWithDepot]

    @extend_schema(
        tags=["Depot Inventory"],
        summary="Déclarer une mise au rebut / casse avec motif obligatoire",
        request=StockScrapRequestSerializer,
        responses={
            200: StockMutationResponseSerializer,
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
            404: ApiErrorSerializer,
            409: ApiErrorSerializer,
        },
    )
    def post(self, request) -> Response:
        depot = get_request_managed_depot(request)
        serializer = StockScrapRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        product = _fetch_product_or_404(data["product_id"])

        stock, movement = services.scrap_depot_stock(
            depot=depot,
            product=product,
            category=data["category"],
            quantity=data["quantity"],
            actor=request.user,
            reason=data["reason"],
        )
        payload = StockMutationResponseSerializer({"stock": stock, "movement": movement}).data
        return Response(payload, status=status.HTTP_200_OK)


class ManagedStockMovementListView(NoStoreResponseMixin, ListAPIView):
    permission_classes = [IsDepotManagerWithDepot]
    serializer_class = StockMovementSerializer

    def get_queryset(self):
        depot = get_request_managed_depot(self.request)
        query = StockMovementFilterQuerySerializer(data=self.request.query_params.dict())
        query.is_valid(raise_exception=True)
        params = query.validated_data
        return selectors.list_depot_stock_movements(
            depot=depot,
            product_id=params.get("product"),
            category=params.get("category"),
            movement_type=params.get("movement_type"),
        )

    @extend_schema(
        tags=["Depot Inventory"],
        summary="Consulter l'historique paginé des mouvements de stock du dépôt",
        parameters=[StockMovementFilterQuerySerializer],
        responses={
            200: StockMovementSerializer(many=True),
            400: ApiErrorSerializer,
            401: ApiErrorSerializer,
            403: ApiErrorSerializer,
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
