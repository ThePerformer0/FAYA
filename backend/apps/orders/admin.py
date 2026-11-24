"""Configuration Django Admin pour les commandes, lignes, historique immuable et paiements."""

from django.contrib import admin

from apps.orders.models import Order, OrderItem, OrderStatusHistory, PaymentRecord


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = (
        "product",
        "operation_type",
        "exchange_brand",
        "quantity",
        "brand_name_snapshot",
        "capacity_kg_snapshot",
        "unit_gas_price",
        "unit_bottle_price",
        "unit_deposit_amount",
        "unit_total_price",
        "line_total_amount",
    )

    def has_add_permission(self, request, obj=None):
        return False


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = ("created_at", "from_status", "to_status", "actor", "reason")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "depot",
        "customer",
        "status",
        "payment_status",
        "total_amount",
        "response_deadline_at",
        "pickup_deadline_at",
        "counted_as_no_show",
        "created_at",
    )
    list_filter = ("status", "payment_status", "counted_as_no_show", "depot")
    search_fields = ("reference", "customer__email", "customer__phone", "depot__name")
    readonly_fields = (
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
        "created_at",
        "updated_at",
    )
    inlines = [OrderItemInline, OrderStatusHistoryInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PaymentRecord)
class PaymentRecordAdmin(admin.ModelAdmin):
    list_display = (
        "order",
        "expected_amount",
        "received_amount",
        "payment_method",
        "status",
        "external_reference",
        "recorded_by",
        "paid_at",
    )
    list_filter = ("payment_method", "status")
    search_fields = ("order__reference", "external_reference")
    readonly_fields = (
        "id",
        "order",
        "expected_amount",
        "received_amount",
        "payment_method",
        "status",
        "external_reference",
        "notes",
        "recorded_by",
        "paid_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
