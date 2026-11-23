"""Vues API publiques du catalogue central."""

from drf_spectacular.utils import extend_schema
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny

from apps.catalog import selectors
from apps.catalog.api.serializers import (
    BrandSerializer,
    ProductFilterQuerySerializer,
    ProductSerializer,
)
from apps.core.api.serializers import ApiErrorSerializer


class BrandListView(ListAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = BrandSerializer
    pagination_class = None

    def get_queryset(self):
        return selectors.list_active_brands()

    @extend_schema(
        tags=["Catalog"],
        summary="Liste des marques actives du catalogue central",
        responses={200: BrandSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class ProductListView(ListAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = ProductSerializer

    def get_queryset(self):
        query = ProductFilterQuerySerializer(data=self.request.query_params.dict())
        query.is_valid(raise_exception=True)
        params = query.validated_data
        return selectors.list_published_products(
            brand_id=params.get("brand"),
            capacity_kg=params.get("capacity_kg"),
            product_type=params.get("product_type"),
        )

    @extend_schema(
        tags=["Catalog"],
        summary="Liste paginée des produits publiés du catalogue central",
        parameters=[ProductFilterQuerySerializer],
        responses={200: ProductSerializer(many=True), 400: ApiErrorSerializer},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
