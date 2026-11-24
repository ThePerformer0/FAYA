from django.urls import path

from apps.orders.api.views import (
    DepotOrderAcceptView,
    DepotOrderCancelNonConformityView,
    DepotOrderDetailView,
    DepotOrderListView,
    DepotOrderPickupView,
    DepotOrderRefuseView,
)

urlpatterns = [
    path("orders/", DepotOrderListView.as_view(), name="depot-portal-orders-list"),
    path("orders/<uuid:order_id>/", DepotOrderDetailView.as_view(), name="depot-portal-orders-detail"),
    path(
        "orders/<uuid:order_id>/accept/",
        DepotOrderAcceptView.as_view(),
        name="depot-portal-orders-accept",
    ),
    path(
        "orders/<uuid:order_id>/refuse/",
        DepotOrderRefuseView.as_view(),
        name="depot-portal-orders-refuse",
    ),
    path(
        "orders/<uuid:order_id>/pickup/",
        DepotOrderPickupView.as_view(),
        name="depot-portal-orders-pickup",
    ),
    path(
        "orders/<uuid:order_id>/cancel-non-conformity/",
        DepotOrderCancelNonConformityView.as_view(),
        name="depot-portal-orders-cancel-non-conformity",
    ),
]
