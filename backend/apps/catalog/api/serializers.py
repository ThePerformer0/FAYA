"""Serializers publics du catalogue central."""

from decimal import Decimal

from rest_framework import serializers

from apps.catalog.models import Brand, Product, ProductType


class BrandSerializer(serializers.ModelSerializer):
    class Meta:
        model = Brand
        fields = ("id", "name", "logo_url")
        read_only_fields = fields


class ProductSerializer(serializers.ModelSerializer):
    brand = BrandSerializer(read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "brand",
            "capacity_kg",
            "product_type",
            "name",
            "description",
            "characteristics",
            "image_url",
        )
        read_only_fields = fields


class ProductFilterQuerySerializer(serializers.Serializer):
    brand = serializers.UUIDField(required=False)
    capacity_kg = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
    )
    product_type = serializers.ChoiceField(choices=ProductType.choices, required=False)
