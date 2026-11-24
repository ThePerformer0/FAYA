"""Serializers du portail Responsable de dépôt (/api/v1/depot/...)."""

from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.api.serializers import BrandSerializer, ProductSerializer
from apps.catalog.models import ProductProposal, ProductType
from apps.depots.api.serializers import OpenStatusFieldMixin
from apps.depots.models import Depot, DepotProductOffer, OfferOperation, OperationType
from apps.inventory.services import EDITABLE_DEPOT_STATUSES


class ManagedDepotSerializer(OpenStatusFieldMixin, serializers.ModelSerializer):
    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)
    open_status = serializers.SerializerMethodField()
    can_order = serializers.SerializerMethodField()
    last_order_time = serializers.SerializerMethodField()
    reopens_at = serializers.SerializerMethodField()
    is_editable = serializers.SerializerMethodField()

    class Meta:
        model = Depot
        fields = (
            "id",
            "name",
            "description",
            "address",
            "neighborhood",
            "phone",
            "latitude",
            "longitude",
            "opening_time",
            "closing_time",
            "status",
            "is_editable",
            "open_status",
            "can_order",
            "last_order_time",
            "reopens_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_is_editable(self, obj: Depot) -> bool:
        return obj.status in EDITABLE_DEPOT_STATUSES


class ManagedDepotUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False)
    description = serializers.CharField(allow_blank=True, required=False)
    address = serializers.CharField(max_length=255, required=False)
    neighborhood = serializers.CharField(max_length=120, allow_blank=True, required=False)
    phone = serializers.CharField(max_length=20, required=False)
    latitude = serializers.FloatField(min_value=-90.0, max_value=90.0, required=False)
    longitude = serializers.FloatField(min_value=-180.0, max_value=180.0, required=False)
    opening_time = serializers.TimeField(required=False)
    closing_time = serializers.TimeField(required=False)

    def validate(self, attrs):
        has_lat = "latitude" in attrs
        has_lng = "longitude" in attrs
        if has_lat != has_lng:
            raise serializers.ValidationError(
                {"coordinates": ["Les paramètres latitude et longitude doivent être fournis ensemble."]}
            )
        return attrs


class ManagedOfferOperationInputSerializer(serializers.Serializer):
    operation_type = serializers.ChoiceField(choices=OperationType.choices)
    is_active = serializers.BooleanField(default=True, required=False)
    gas_price = serializers.IntegerField(min_value=0)
    bottle_price = serializers.IntegerField(min_value=0, default=0, required=False)
    deposit_amount = serializers.IntegerField(min_value=0, default=0, required=False)


class ManagedOfferOperationSerializer(serializers.ModelSerializer):
    total_unit_price = serializers.IntegerField(read_only=True)

    class Meta:
        model = OfferOperation
        fields = (
            "id",
            "operation_type",
            "is_active",
            "gas_price",
            "bottle_price",
            "deposit_amount",
            "total_unit_price",
        )
        read_only_fields = fields


class ManagedOfferSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    operations = ManagedOfferOperationSerializer(many=True, read_only=True)
    exchange_brands = serializers.SerializerMethodField()

    class Meta:
        model = DepotProductOffer
        fields = (
            "id",
            "product",
            "is_active",
            "notes",
            "operations",
            "exchange_brands",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(BrandSerializer(many=True))
    def get_exchange_brands(self, obj: DepotProductOffer) -> list[dict]:
        brands = [item.accepted_brand for item in obj.exchange_brands.all()]
        return BrandSerializer(brands, many=True).data


class ManagedOfferCreateSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    is_active = serializers.BooleanField(default=True, required=False)
    notes = serializers.CharField(allow_blank=True, default="", required=False)
    operations = ManagedOfferOperationInputSerializer(many=True, required=False)
    exchange_brand_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
    )


class ManagedOfferUpdateSerializer(serializers.Serializer):
    is_active = serializers.BooleanField(required=False)
    notes = serializers.CharField(allow_blank=True, required=False)
    operations = ManagedOfferOperationInputSerializer(many=True, required=False)
    exchange_brand_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
    )


class ManagedProductProposalSerializer(serializers.ModelSerializer):
    created_product = ProductSerializer(read_only=True)

    class Meta:
        model = ProductProposal
        fields = (
            "id",
            "proposed_brand_name",
            "capacity_kg",
            "product_type",
            "name",
            "description",
            "status",
            "review_note",
            "reviewed_at",
            "created_product",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ManagedProductProposalCreateSerializer(serializers.Serializer):
    proposed_brand_name = serializers.CharField(max_length=100)
    capacity_kg = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.01"),
    )
    product_type = serializers.ChoiceField(
        choices=ProductType.choices,
        default=ProductType.BUTANE,
    )
    name = serializers.CharField(max_length=150)
    description = serializers.CharField(allow_blank=True, default="", required=False)
