from django.apps import AppConfig


class QualityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.quality"
    label = "quality"
    verbose_name = "Qualite et HACCP"

    def ready(self) -> None:
        # L0-3 : declaration des commandes periodiques de ce module
        # (registre `core.services.scheduled_commands`). Declare seulement —
        # l'ecriture des planifications est faite au deploiement par
        # `apps.core.tasks.sync_schedules`.
        from apps.quality.services.scheduling_registration import register_scheduled_commands

        register_scheduled_commands()
