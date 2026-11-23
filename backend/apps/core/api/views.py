"""Endpoint de santé vérifiant la disponibilité de l'API et de PostgreSQL."""

from django.db import connection
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.serializers import HealthCheckSerializer, PublicPlatformSettingSerializer
from apps.core.models import PlatformSetting


class HealthCheckView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["System"],
        summary="État de santé de l'API et de la base de données",
        responses={200: HealthCheckSerializer, 503: HealthCheckSerializer},
    )
    def get(self, request) -> Response:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return Response({"status": "ok", "database": "ok"}, status=status.HTTP_200_OK)
        except Exception:
            return Response(
                {"status": "degraded", "database": "error"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )


class PublicPlatformSettingsView(APIView):
    """Expose les paramètres opérationnels publics et l'heure serveur (DESIGN_SYSTEM §2.4, §4.5)."""

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        tags=["System"],
        summary="Paramètres globaux publics et horloge serveur",
        responses={200: PublicPlatformSettingSerializer},
    )
    def get(self, request) -> Response:
        cfg = PlatformSetting.load()
        data = {
            "timezone": cfg.timezone,
            "order_response_timeout_minutes": cfg.order_response_timeout_minutes,
            "order_pickup_timeout_minutes": cfg.order_pickup_timeout_minutes,
            "order_cutoff_before_close_minutes": cfg.order_cutoff_before_close_minutes,
            "closing_soon_threshold_minutes": cfg.closing_soon_threshold_minutes,
            "max_quantity_per_order": cfg.max_quantity_per_order,
            "max_active_orders_per_customer": cfg.max_active_orders_per_customer,
            "no_show_threshold": cfg.no_show_threshold,
            "no_show_window_days": cfg.no_show_window_days,
            "suspension_duration_days": cfg.suspension_duration_days,
            "server_now": timezone.now(),
        }
        serializer = PublicPlatformSettingSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)
