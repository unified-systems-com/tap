from django.apps import AppConfig


class TapFilesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "tap_files"
    verbose_name = "TAP Files"

    def ready(self) -> None:
        # Registration only: the backend setting is checked by Django's system checks, so a wrong
        # value fails startup with a named error (req-tap-files-interface-3) without crash-looping
        # inside ready().
        from tap_files import checks  # noqa: F401
