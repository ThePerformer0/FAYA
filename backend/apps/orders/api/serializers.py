"""Serializers API commandes client (/api/v1/orders/...) et dépôt (/api/v1/depot/orders/...)."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import User
from apps.depots.models import Depot, OperationType
from apps.inventory.api.serializers import StrictIntegerField
from apps.inventory.services import MAX_STOCK_QUANTITY
from apps.orders.models import (
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentMethod,
    PaymentRecord,
)


class OrderFilterQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=OrderStatus.choices, required=False)


class OrderCreateRequestSerializer(serializers.Serializer):
    depot_id = serializers.UUIDField()
    product_id = serializers.UUIDField()
    operation_type = serializers.ChoiceField(choices=OperationType.choices)
    quantity = StrictIntegerField(min_value=1, max_value=MAX_STOCK_QUANTITY)
    exchange_brand_id = serializers.UUIDField(required=False, allow_null=True)


class OrderCancelRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(allow_blank=True, default="", required=False, max_length=500)


class OrderReasonRequiredRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class OrderPickupRequestSerializer(serializers.Serializer):
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices)
    received_amount = StrictIntegerField(min_value=0, max_value=MAX_STOCK_QUANTITY, required=False)
    external_reference = serializers.CharField(
        allow_blank=True, default="", required=False, max_length=120
    )
    notes = serializers.CharField(allow_blank=True, default="", required=False, max_length=500)


class OrderDepotSummarySerializer(serializers.ModelSerializer):
    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)

    class Meta:
        model = Depot
        fields = (
            "id",
            "name",
            "address",
            "neighborhood",
            "phone",
            "opening_time",
            "closing_time",
            "latitude",
            "longitude",
        )
        read_only_fields = fields


class OrderCustomerSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("full_name", "phone")
        read_only_fields = fields


class OrderItemSerializer(serializers.ModelSerializer):
    product_id = serializers.UUIDField(read_only=True)
    brand_name = serializers.CharField(source="brand_name_snapshot", read_only=True)
    product_name = serializers.CharField(source="product_name_snapshot", read_only=True)
    capacity_kg = serializers.DecimalField(
        source="capacity_kg_snapshot",
        max_digits=5,
        decimal_places=2,
        read_only=True,
    )
    exchange_brand_name = serializers.CharField(
        source="exchange_brand_name_snapshot", read_only=True
    )

    class Meta:
        model = OrderItem
        fields = (
            "id",
            "product_id",
            "brand_name",
            "product_name",
            "capacity_kg",
            "operation_type",
            "exchange_brand_name",
            "quantity",
            "unit_gas_price",
            "unit_bottle_price",
            "unit_deposit_amount",
            "unit_total_price",
            "line_total_amount",
        )
        read_only_fields = fields


class OrderStatusHistorySerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = OrderStatusHistory
        fields = ("id", "from_status", "to_status", "reason", "actor_name", "created_at")
        read_only_fields = fields

    def get_actor_name(self, obj: OrderStatusHistory) -> str | None:
        return obj.actor.full_name if obj.actor else None


class PaymentRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentRecord
        fields = (
            "id",
            "expected_amount",
            "received_amount",
            "payment_method",
            "status",
            "external_reference",
            "notes",
            "paid_at",
        )
        read_only_fields = fields


class CustomerOrderSerializer(serializers.ModelSerializer):
    depot = OrderDepotSummarySerializer(read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    payment = serializers.SerializerMethodField()
    status_history = OrderStatusHistorySerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = (
            "id",
            "reference",
            "depot",
            "status",
            "payment_status",
            "total_amount",
            "response_deadline_at",
            "pickup_deadline_at",
            "confirmed_at",
            "picked_up_at",
            "refused_at",
            "cancelled_at",
            "expired_at",
            "status_reason",
            "cancellation_source",
            "counted_as_no_show",
            "items",
            "payment",
            "status_history",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(PaymentRecordSerializer(allow_null=True))
    def get_payment(self, obj: Order) -> dict | None:
        try:
            payment = obj.payment_record
        except PaymentRecord.DoesNotExist:
            return None
        return PaymentRecordSerializer(payment).data


class DepotOrderSerializer(CustomerOrderSerializer):
    customer = OrderCustomerSummarySerializer(read_only=True)

    class Meta(CustomerOrderSerializer.Meta):
        fields = (
            "id",
            "reference",
            "customer",
            "depot",
            "status",
            "payment_status",
            "total_amount",
            "response_deadline_at",
            "pickup_deadline_at",
            "confirmed_at",
            "picked_up_at",
            "refused_at",
            "cancelled_at",
            "expired_at",
            "status_reason",
            "cancellation_source",
            "counted_as_no_show",
            "items",
            "payment",
            "status_history",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields
