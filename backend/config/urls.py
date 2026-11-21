"""Routage racine du monolithe modulaire Faya."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.api.views import HealthCheckView
from apps.core.exceptions import json_handler404

admin.site.site_header = "Faya — Administration"
admin.site.site_title = "Faya Admin"
admin.site.index_title = "Tableau de bord de la plateforme"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/health/", HealthCheckView.as_view(), name="health-check"),
    path("api/v1/auth/", include("apps.accounts.api.urls")),
]

if settings.DEBUG:
    urlpatterns += [
        path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
        path(
            "api/v1/docs/",
            SpectacularSwaggerView.as_view(url_name="schema"),
            name="swagger-ui",
        ),
    ]

# Toute route /api/* non reconnue renvoie le format d'erreur JSON unifié
urlpatterns += [
    re_path(r"^api/.*", json_handler404),
]

handler404 = "apps.core.exceptions.json_handler404"
handler500 = "apps.core.exceptions.json_handler500"
