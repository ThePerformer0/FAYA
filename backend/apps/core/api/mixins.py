"""Mixins DRF transversaux."""


class NoStoreResponseMixin:
    """Empêche toute mise en cache HTTP des réponses authentifiées ou sensibles."""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response
