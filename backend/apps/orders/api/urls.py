from django.urls import path

from apps.orders.api.views import (
    CustomerOrderCancelView,
    CustomerOrderDetailView,
    CustomerOrderListCreateView,
)

urlpatterns = [
    path("", CustomerOrderListCreateView.as_view(), name="customer-orders-list-create"),
    path("<uuid:order_id>/", CustomerOrderDetailView.as_view(), name="customer-orders-detail"),
    path(
        "<uuid:order_id>/cancel/",
        CustomerOrderCancelView.as_view(),
        name="customer-orders-cancel",
    ),
]
