from django.apps import AppConfig


class LogisticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.logistics"
    label = "logistics"
    verbose_name = "Logistique"

    def ready(self) -> None:
        # §5.11 reporting (REP5) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que
        # `core.events` — jamais un import direct par `apps.reporting`.
        from apps.logistics.services.ai_context_registration import register_ai_context
        from apps.logistics.services.reports_registration import register_reports

        register_reports()
        # AI2 (assistant contextuel par page/action) : meme patron, registre
        # partage `core.services.ai_context_registry`.
        register_ai_context()
