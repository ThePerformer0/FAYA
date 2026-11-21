"""Serializers DRF pour l'authentification JWT hybride et le profil."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import CustomerSuspension, User, phone_e164_validator
from apps.accounts.selectors import get_active_suspension


class ActiveSuspensionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerSuspension
        fields = ("id", "starts_at", "ends_at", "reason")
        read_only_fields = fields


class UserMeSerializer(serializers.ModelSerializer):
    active_suspension = serializers.SerializerMethodField()
    managed_depot_id = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "phone",
            "full_name",
            "role",
            "active_suspension",
            "managed_depot_id",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(ActiveSuspensionSerializer(allow_null=True))
    def get_active_suspension(self, obj: User) -> dict | None:
        suspension = get_active_suspension(user=obj)
        if suspension is None:
            return None
        return ActiveSuspensionSerializer(suspension).data

    def get_managed_depot_id(self, obj: User) -> str | None:
        depot = getattr(obj, "managed_depot", None)
        return str(depot.pk) if depot is not None else None


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20, validators=[phone_e164_validator])
    full_name = serializers.CharField(max_length=150, min_length=2)
    password = serializers.CharField(write_only=True, min_length=8)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class UpdateProfileSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=150, min_length=2, required=False)
    phone = serializers.CharField(
        max_length=20,
        validators=[phone_e164_validator],
        required=False,
    )


class AuthResponseSerializer(serializers.Serializer):
    access_token = serializers.CharField()
    user = UserMeSerializer()


class TokenRefreshResponseSerializer(serializers.Serializer):
    access_token = serializers.CharField()
