"""Administration Django des dépôts et de leurs offres (carte PostGIS & badges Faya)."""

from django.contrib import admin, messages
from django.contrib.gis import admin as gis_admin
from django.utils.html import format_html

from apps.core.exceptions import DomainError
from apps.depots.models import (
    Depot,
    DepotProductOffer,
    DepotStatus,
    OfferExchangeBrand,
    OfferOperation,
)
from apps.depots.services import change_depot_status


class OfferOperationInline(admin.TabularInline):
    model = OfferOperation
    extra = 1


class OfferExchangeBrandInline(admin.TabularInline):
    model = OfferExchangeBrand
    extra = 1


@admin.register(Depot)
class DepotAdmin(gis_admin.GISModelAdmin):
    list_display = (
        "name",
        "neighborhood",
        "manager",
        "phone",
        "opening_time",
        "closing_time",
        "status_badge",
        "updated_at",
    )
    list_filter = ("status", "neighborhood")
    search_fields = ("name", "address", "neighborhood", "phone", "manager__email")
    readonly_fields = ("id", "created_at", "updated_at")
    actions = ["validate_selected_depots", "suspend_selected_depots"]

    @admin.display(description="Statut")
    def status_badge(self, obj: Depot) -> str:
        css = obj.status.lower()
        return format_html(
            '<span class="faya-badge faya-badge--{}">{}</span>',
            css,
            obj.get_status_display(),
        )

    @admin.action(description="Valider les dépôts sélectionnés")
    def validate_selected_depots(self, request, queryset) -> None:
        count = 0
        for depot in queryset.exclude(status=DepotStatus.ACTIVE):
            try:
                change_depot_status(
                    depot=depot,
                    new_status=DepotStatus.ACTIVE,
                    actor=request.user,
                    reason="Validation depuis l'administration Django.",
                )
                count += 1
            except DomainError as exc:
                self.message_user(request, exc.message, level=messages.WARNING)
        if count:
            self.message_user(
                request,
                f"{count} dépôt(s) validé(s) et journalisé(s).",
                level=messages.SUCCESS,
            )

    @admin.action(description="Suspendre les dépôts sélectionnés")
    def suspend_selected_depots(self, request, queryset) -> None:
        count = 0
        for depot in queryset.exclude(status=DepotStatus.SUSPENDED):
            try:
                change_depot_status(
                    depot=depot,
                    new_status=DepotStatus.SUSPENDED,
                    actor=request.user,
                    reason="Suspension depuis l'administration Django.",
                )
                count += 1
            except DomainError as exc:
                self.message_user(request, exc.message, level=messages.WARNING)
        if count:
            self.message_user(
                request,
                f"{count} dépôt(s) suspendu(s) et journalisé(s).",
                level=messages.SUCCESS,
            )


@admin.register(DepotProductOffer)
class DepotProductOfferAdmin(admin.ModelAdmin):
    list_display = ("depot", "product", "is_active", "updated_at")
    list_filter = ("is_active", "depot", "product__brand")
    search_fields = ("depot__name", "product__name", "product__brand__name")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [OfferOperationInline, OfferExchangeBrandInline]
