from django.db import migrations


def create_default_platform_settings(apps, schema_editor) -> None:
    PlatformSetting = apps.get_model("core", "PlatformSetting")
    PlatformSetting.objects.get_or_create(pk=1)


def remove_default_platform_settings(apps, schema_editor) -> None:
    PlatformSetting = apps.get_model("core", "PlatformSetting")
    PlatformSetting.objects.filter(pk=1).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            create_default_platform_settings,
            reverse_code=remove_default_platform_settings,
        ),
    ]
