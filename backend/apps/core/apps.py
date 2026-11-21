from django.apps import AppConfig
from django.db.models.signals import post_migrate


def ensure_platform_settings(sender, **kwargs) -> None:
    """Garantit la présence du singleton PlatformSetting après migrate ou flush."""
    from apps.core.models import PlatformSetting

    PlatformSetting.objects.get_or_create(pk=1)


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Socle & Paramètres"

    def ready(self) -> None:
        post_migrate.connect(ensure_platform_settings, sender=self)
