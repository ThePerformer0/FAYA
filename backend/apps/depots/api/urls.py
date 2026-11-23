from django.urls import path

from apps.depots.api.views import PublicDepotDetailView, PublicDepotListView

urlpatterns = [
    path("", PublicDepotListView.as_view(), name="depots-list"),
    path("<uuid:depot_id>/", PublicDepotDetailView.as_view(), name="depots-detail"),
]
