"""Serializers API du module stocks & mouvements (/api/v1/depot/stocks/...)."""

from rest_framework import serializers

from apps.catalog.api.serializers import ProductSerializer
from apps.inventory.models import (
    DepotStock,
    StockCategory,
    StockMovement,
    StockMovementType,
)


class DepotStockSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    available_quantity = serializers.IntegerField(read_only=True)

    class Meta:
        model = DepotStock
        fields = (
            "id",
            "product",
            "category",
            "physical_quantity",
            "reserved_quantity",
            "available_quantity",
            "updated_at",
        )
        read_only_fields = fields


class StockMovementSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = StockMovement
        fields = (
            "id",
            "product",
            "category",
            "movement_type",
            "quantity_before",
            "quantity_after",
            "delta",
            "reason",
            "actor_name",
            "created_at",
        )
        read_only_fields = fields

    def get_actor_name(self, obj: StockMovement) -> str | None:
        return obj.actor.full_name if obj.actor else None


class StockMutationResponseSerializer(serializers.Serializer):
    stock = DepotStockSerializer(read_only=True)
    movement = StockMovementSerializer(read_only=True)


class StockFilterQuerySerializer(serializers.Serializer):
    product = serializers.UUIDField(required=False)
    category = serializers.ChoiceField(choices=StockCategory.choices, required=False)


class StockMovementFilterQuerySerializer(serializers.Serializer):
    product = serializers.UUIDField(required=False)
    category = serializers.ChoiceField(choices=StockCategory.choices, required=False)
    movement_type = serializers.ChoiceField(choices=StockMovementType.choices, required=False)


class StockRestockRequestSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    category = serializers.ChoiceField(choices=StockCategory.choices)
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(allow_blank=True, default="", required=False, max_length=500)


class StockAdjustRequestSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    category = serializers.ChoiceField(choices=StockCategory.choices)
    new_physical_quantity = serializers.IntegerField(min_value=0)
    movement_type = serializers.ChoiceField(
        choices=[
            (StockMovementType.INVENTORY_CORRECTION, StockMovementType.INVENTORY_CORRECTION.label),
            (StockMovementType.MANUAL_ADJUSTMENT, StockMovementType.MANUAL_ADJUSTMENT.label),
        ],
        default=StockMovementType.INVENTORY_CORRECTION,
        required=False,
    )
    reason = serializers.CharField(max_length=500)
    expected_physical_quantity = serializers.IntegerField(min_value=0, required=False)


class StockScrapRequestSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    category = serializers.ChoiceField(choices=StockCategory.choices)
    quantity = serializers.IntegerField(min_value=1)
    reason = serializers.CharField(max_length=500)
