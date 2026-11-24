"""Configuration Django Admin pour les stocks et mouvements (lecture seule sur le journal)."""

from django.contrib import admin

from apps.inventory.models import DepotStock, StockMovement, StockReservation


@admin.register(DepotStock)
class DepotStockAdmin(admin.ModelAdmin):
    list_display = (
        "depot",
        "product",
        "category",
        "physical_quantity",
        "reserved_quantity",
        "available_display",
        "updated_at",
    )
    list_filter = ("category", "depot__status", "product__brand")
    search_fields = ("depot__name", "product__name", "product__brand__name")
    readonly_fields = ("id", "reserved_quantity", "created_at", "updated_at")
    autocomplete_fields = ("depot", "product")

    @admin.display(description="Disponible")
    def available_display(self, obj: DepotStock) -> int:
        return obj.available_quantity


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "depot",
        "product",
        "category",
        "movement_type",
        "quantity_before",
        "delta",
        "quantity_after",
        "actor",
    )
    list_filter = ("movement_type", "category", "depot")
    search_fields = ("depot__name", "product__name", "reason", "actor__email")
    readonly_fields = (
        "id",
        "depot",
        "product",
        "category",
        "movement_type",
        "quantity_before",
        "quantity_after",
        "delta",
        "reason",
        "actor",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockReservation)
class StockReservationAdmin(admin.ModelAdmin):
    list_display = ("order", "stock", "quantity", "status", "expires_at", "created_at")
    list_filter = ("status", "stock__category")
    search_fields = ("order__reference", "stock__depot__name", "stock__product__name")
    readonly_fields = (
        "id",
        "order",
        "stock",
        "quantity",
        "status",
        "expires_at",
        "released_at",
        "consumed_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
