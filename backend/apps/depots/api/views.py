"""Vues API publiques de recherche et consultation des dépôts."""

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.serializers import ApiErrorSerializer
from apps.core.models import PlatformSetting
from apps.depots import selectors
from apps.depots.api.serializers import (
    DepotSearchQuerySerializer,
    PublicDepotDetailSerializer,
    PublicDepotListSerializer,
)


class PublicDepotListView(ListAPIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = PublicDepotListSerializer

    def _get_query_params(self) -> dict:
        if not hasattr(self, "_validated_params"):
            serializer = DepotSearchQuerySerializer(data=self.request.query_params)
            serializer.is_valid(raise_exception=True)
            self._validated_params = serializer.validated_data
        return self._validated_params

    def _get_snapshot_context(self) -> tuple[PlatformSetting, object]:
        if not hasattr(self, "_snapshot_ctx"):
            self._snapshot_ctx = (PlatformSetting.load(), timezone.now())
        return self._snapshot_ctx

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        cfg, now = self._get_snapshot_context()
        ctx["platform_settings"] = cfg
        ctx["reference_now"] = now
        return ctx

    def get_queryset(self):
        params = self._get_query_params()
        cfg, now = self._get_snapshot_context()
        return selectors.search_public_depots(
            lat=params.get("lat"),
            lng=params.get("lng"),
            radius_km=params.get("radius_km"),
            q=params.get("q"),
            brand_id=params.get("brand"),
            capacity_kg=params.get("capacity_kg"),
            operation_type=params.get("operation"),
            open_now=params.get("open_now", False),
            settings_obj=cfg,
            at=now,
        )

    @extend_schema(
        tags=["Depots"],
        summary="Rechercher les dépôts actifs par proximité et filtres",
        parameters=[DepotSearchQuerySerializer],
        responses={200: PublicDepotListSerializer(many=True), 400: ApiErrorSerializer},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class PublicDepotDetailView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["Depots"],
        summary="Fiche publique détaillée d'un dépôt actif",
        responses={200: PublicDepotDetailSerializer, 404: ApiErrorSerializer},
    )
    def get(self, request, depot_id) -> Response:
        depot = selectors.get_public_depot_detail(depot_id=depot_id)
        serializer = PublicDepotDetailSerializer(
            depot,
            context={
                "request": request,
                "platform_settings": PlatformSetting.load(),
                "reference_now": timezone.now(),
            },
        )
        return Response(serializer.data, status=status.HTTP_200_OK)
