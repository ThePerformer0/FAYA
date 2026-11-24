"""Routage privé du portail Responsable de dépôt (/api/v1/depot/...)."""

from django.urls import include, path

from apps.depots.api.portal_views import (
    ManagedDepotView,
    ManagedOfferDetailView,
    ManagedOfferListCreateView,
    ManagedProposalListCreateView,
)

urlpatterns = [
    path("", ManagedDepotView.as_view(), name="depot-portal-me"),
    path("offers/", ManagedOfferListCreateView.as_view(), name="depot-portal-offers"),
    path(
        "offers/<uuid:offer_id>/",
        ManagedOfferDetailView.as_view(),
        name="depot-portal-offer-detail",
    ),
    path(
        "proposals/",
        ManagedProposalListCreateView.as_view(),
        name="depot-portal-proposals",
    ),
    path("", include("apps.inventory.api.urls")),
]
