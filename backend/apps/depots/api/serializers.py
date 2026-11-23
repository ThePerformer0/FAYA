"""Serializers publics de recherche et fiche détaillée des dépôts."""

from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.api.serializers import BrandSerializer, ProductSerializer
from apps.depots.models import Depot, DepotProductOffer, OfferOperation, OperationType
from apps.depots.selectors import DepotOpenState, compute_depot_open_state


class DepotSearchQuerySerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90.0, max_value=90.0, required=False)
    lng = serializers.FloatField(min_value=-180.0, max_value=180.0, required=False)
    radius_km = serializers.FloatField(min_value=0.1, max_value=200.0, required=False)
    q = serializers.CharField(max_length=120, required=False, allow_blank=True)
    brand = serializers.UUIDField(required=False)
    capacity_kg = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
    )
    operation = serializers.ChoiceField(choices=OperationType.choices, required=False)
    open_now = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        has_lat = "lat" in attrs
        has_lng = "lng" in attrs
        if has_lat != has_lng:
            raise serializers.ValidationError(
                {"coordinates": ["Les paramètres lat et lng doivent être fournis ensemble."]}
            )
        if "radius_km" in attrs and not (has_lat and has_lng):
            raise serializers.ValidationError(
                {"radius_km": ["Le paramètre radius_km nécessite lat et lng."]}
            )
        return attrs


class PublicOfferOperationSerializer(serializers.ModelSerializer):
    total_unit_price = serializers.IntegerField(read_only=True)

    class Meta:
        model = OfferOperation
        fields = (
            "operation_type",
            "gas_price",
            "bottle_price",
            "deposit_amount",
            "total_unit_price",
        )
        read_only_fields = fields


class PublicDepotOfferSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    operations = serializers.SerializerMethodField()
    exchange_brands = serializers.SerializerMethodField()

    class Meta:
        model = DepotProductOffer
        fields = (
            "id",
            "product",
            "notes",
            "operations",
            "exchange_brands",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(PublicOfferOperationSerializer(many=True))
    def get_operations(self, obj: DepotProductOffer) -> list[dict]:
        ops = getattr(obj, "active_operations", None)
        if ops is None:
            ops = obj.operations.filter(is_active=True).order_by("operation_type")
        return PublicOfferOperationSerializer(ops, many=True).data

    @extend_schema_field(BrandSerializer(many=True))
    def get_exchange_brands(self, obj: DepotProductOffer) -> list[dict]:
        items = getattr(obj, "active_exchange_brands", None)
        if items is None:
            items = obj.exchange_brands.select_related("accepted_brand").filter(
                accepted_brand__is_active=True
            )
        brands = [item.accepted_brand for item in items]
        return BrandSerializer(brands, many=True).data


class OpenStatusFieldMixin:
    def _open_state(self, obj: Depot) -> DepotOpenState:
        cache_attr = "_cached_open_state"
        cached = getattr(obj, cache_attr, None)
        if cached is None:
            cached = compute_depot_open_state(
                depot=obj,
                settings_obj=self.context.get("platform_settings"),
                at=self.context.get("reference_now"),
            )
            setattr(obj, cache_attr, cached)
        return cached

    def get_open_status(self, obj: Depot) -> str:
        return self._open_state(obj).open_status

    def get_can_order(self, obj: Depot) -> bool:
        return self._open_state(obj).can_order

    def get_last_order_time(self, obj: Depot) -> str:
        return self._open_state(obj).last_order_time.strftime("%H:%M")

    def get_reopens_at(self, obj: Depot) -> str:
        return self._open_state(obj).reopens_at.strftime("%H:%M")


class PublicDepotListSerializer(OpenStatusFieldMixin, serializers.ModelSerializer):
    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)
    distance_meters = serializers.SerializerMethodField()
    open_status = serializers.SerializerMethodField()
    can_order = serializers.SerializerMethodField()
    last_order_time = serializers.SerializerMethodField()
    reopens_at = serializers.SerializerMethodField()
    offers = serializers.SerializerMethodField()

    class Meta:
        model = Depot
        fields = (
            "id",
            "name",
            "address",
            "neighborhood",
            "phone",
            "latitude",
            "longitude",
            "distance_meters",
            "opening_time",
            "closing_time",
            "open_status",
            "can_order",
            "last_order_time",
            "reopens_at",
            "offers",
            "updated_at",
        )
        read_only_fields = fields

    def get_distance_meters(self, obj: Depot) -> int | None:
        dist = getattr(obj, "distance_geo", None)
        if dist is None:
            return None
        return round(dist.m)

    @extend_schema_field(PublicDepotOfferSerializer(many=True))
    def get_offers(self, obj: Depot) -> list[dict]:
        offers = getattr(obj, "public_offers", [])
        return PublicDepotOfferSerializer(offers, many=True).data


class PublicDepotDetailSerializer(PublicDepotListSerializer):
    class Meta(PublicDepotListSerializer.Meta):
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
            "open_status",
            "can_order",
            "last_order_time",
            "reopens_at",
            "offers",
            "updated_at",
        )
        read_only_fields = fields
