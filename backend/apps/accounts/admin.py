"""Administration Django des utilisateurs et des suspensions clients."""

from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import CustomerSuspension, User
from apps.accounts.services import lift_suspension
from apps.core.exceptions import DomainError


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("-created_at",)
    list_display = ("email", "full_name", "phone", "role", "is_active", "is_staff", "created_at")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("email", "full_name", "phone")
    readonly_fields = ("id", "last_login", "created_at", "updated_at")

    fieldsets = (
        (None, {"fields": ("id", "email", "password")}),
        ("Identité", {"fields": ("full_name", "phone", "role")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Dates", {"fields": ("last_login", "created_at", "updated_at")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "full_name", "phone", "role", "password1", "password2"),
            },
        ),
    )


@admin.register(CustomerSuspension)
class CustomerSuspensionAdmin(admin.ModelAdmin):
    list_display = (
        "customer",
        "reason",
        "triggering_no_show_count",
        "starts_at",
        "ends_at",
        "lifted_at",
        "lifted_by",
    )
    list_filter = ("reason", "lifted_at")
    search_fields = ("customer__email", "customer__phone", "customer__full_name")
    readonly_fields = ("id", "lifted_at", "lifted_by", "created_at", "updated_at")
    actions = ["lift_selected_suspensions"]

    @admin.action(description="Lever de manière anticipée les suspensions sélectionnées")
    def lift_selected_suspensions(self, request, queryset) -> None:
        lifted_count = 0
        for suspension in queryset.filter(lifted_at__isnull=True):
            try:
                lift_suspension(
                    suspension=suspension,
                    actor=request.user,
                    reason="Levée manuelle depuis l'administration Django.",
                )
                lifted_count += 1
            except DomainError as exc:
                self.message_user(request, str(exc.message), level=messages.WARNING)
        if lifted_count:
            self.message_user(
                request,
                f"{lifted_count} suspension(s) levée(s) et journalisée(s).",
                level=messages.SUCCESS,
            )
