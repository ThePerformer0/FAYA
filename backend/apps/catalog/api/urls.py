from django.urls import path

from apps.catalog.api.views import BrandListView, ProductListView

urlpatterns = [
    path("brands/", BrandListView.as_view(), name="catalog-brands"),
    path("products/", ProductListView.as_view(), name="catalog-products"),
]
