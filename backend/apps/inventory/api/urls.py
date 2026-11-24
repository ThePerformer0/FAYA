from django.urls import path

from apps.inventory.api.views import (
    ManagedStockAdjustView,
    ManagedStockListView,
    ManagedStockMovementListView,
    ManagedStockRestockView,
    ManagedStockScrapView,
)

urlpatterns = [
    path("stocks/", ManagedStockListView.as_view(), name="depot-portal-stocks"),
    path("stocks/restock/", ManagedStockRestockView.as_view(), name="depot-portal-stocks-restock"),
    path("stocks/adjust/", ManagedStockAdjustView.as_view(), name="depot-portal-stocks-adjust"),
    path("stocks/scrap/", ManagedStockScrapView.as_view(), name="depot-portal-stocks-scrap"),
    path(
        "stock-movements/",
        ManagedStockMovementListView.as_view(),
        name="depot-portal-stock-movements",
    ),
]
