"""Endpoint de santé vérifiant la disponibilité de l'API et de PostgreSQL."""

from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.serializers import HealthCheckSerializer


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
