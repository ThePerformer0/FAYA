"""Administration Django pour les paramètres globaux et le journal d'audit."""

from django.contrib import admin

from apps.core.models import AuditLog, PlatformSetting


@admin.register(PlatformSetting)
class PlatformSettingAdmin(admin.ModelAdmin):
    list_display = (
        "timezone",
        "order_response_timeout_minutes",
        "order_pickup_timeout_minutes",
        "order_cutoff_before_close_minutes",
        "max_quantity_per_order",
        "no_show_threshold",
        "suspension_duration_days",
        "updated_at",
    )

    def has_add_permission(self, request) -> bool:
        return not PlatformSetting.objects.exists()

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "resource_type", "resource_id", "actor")
    list_filter = ("action", "resource_type", "created_at")
    search_fields = ("resource_id", "reason", "actor__email")
    readonly_fields = (
        "id",
        "actor",
        "action",
        "resource_type",
        "resource_id",
        "before_state",
        "after_state",
        "reason",
        "created_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
