from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.analytics"
    label = "analytics"
    verbose_name = "Analytique (entrepôt & indicateurs)"

    def ready(self) -> None:
        # L0-3 : declaration des commandes periodiques de ce module
        # (registre `core.services.scheduled_commands`). Declare seulement —
        # l'ecriture des planifications est faite au deploiement par
        # `apps.core.tasks.sync_schedules`.
        from apps.analytics.services.scheduling_registration import register_scheduled_commands

        register_scheduled_commands()
