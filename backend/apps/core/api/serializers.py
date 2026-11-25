from datetime import UTC

from rest_framework import serializers


class HealthCheckSerializer(serializers.Serializer):
    status = serializers.CharField()
    database = serializers.CharField()


class ApiErrorSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    details = serializers.DictField(required=False)


class PublicPlatformSettingSerializer(serializers.Serializer):
    timezone = serializers.CharField()
    order_response_timeout_minutes = serializers.IntegerField()
    order_pickup_timeout_minutes = serializers.IntegerField()
    order_cutoff_before_close_minutes = serializers.IntegerField()
    closing_soon_threshold_minutes = serializers.IntegerField()
    max_quantity_per_order = serializers.IntegerField()
    max_active_orders_per_customer = serializers.IntegerField()
    no_show_threshold = serializers.IntegerField()
    no_show_window_days = serializers.IntegerField()
    suspension_duration_days = serializers.IntegerField()
    server_now = serializers.DateTimeField(default_timezone=UTC)
