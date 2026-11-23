"""Administration Django du catalogue central (badges Faya & actions auditées)."""

from django.contrib import admin, messages
from django.utils.html import format_html

from apps.catalog.models import Brand, Product, ProductProposal, ProductProposalStatus
from apps.catalog.services import approve_product_proposal
from apps.core.exceptions import DomainError


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "brand", "capacity_kg", "product_type", "status_badge", "updated_at")
    list_filter = ("status", "brand", "product_type")
    search_fields = ("name", "brand__name", "description")
    readonly_fields = ("id", "created_at", "updated_at")

    @admin.display(description="Statut")
    def status_badge(self, obj: Product) -> str:
        css = obj.status.lower()
        return format_html(
            '<span class="faya-badge faya-badge--{}">{}</span>',
            css,
            obj.get_status_display(),
        )


@admin.register(ProductProposal)
class ProductProposalAdmin(admin.ModelAdmin):
    list_display = (
        "proposed_brand_name",
        "capacity_kg",
        "product_type",
        "depot",
        "status_badge",
        "created_at",
    )
    list_filter = ("status", "product_type", "created_at")
    search_fields = ("proposed_brand_name", "name", "depot__name")
    readonly_fields = ("id", "reviewed_by", "reviewed_at", "created_product", "created_at", "updated_at")
    actions = ["approve_selected_proposals"]

    @admin.display(description="Statut")
    def status_badge(self, obj: ProductProposal) -> str:
        css = obj.status.lower()
        return format_html(
            '<span class="faya-badge faya-badge--{}">{}</span>',
            css,
            obj.get_status_display(),
        )

    @admin.action(description="Approuver les propositions sélectionnées (et publier)")
    def approve_selected_proposals(self, request, queryset) -> None:
        approved = 0
        for proposal in queryset.filter(status=ProductProposalStatus.PENDING):
            try:
                approve_product_proposal(
                    proposal=proposal,
                    actor=request.user,
                    review_note="Validée depuis l'administration Django.",
                )
                approved += 1
            except DomainError as exc:
                self.message_user(request, exc.message, level=messages.WARNING)
        if approved:
            self.message_user(
                request,
                f"{approved} proposition(s) approuvée(s) et publiée(s).",
                level=messages.SUCCESS,
            )
