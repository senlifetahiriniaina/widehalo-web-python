from django.apps import AppConfig


class SalesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sales"
    label = "sales"
    verbose_name = "Ventes"

    def ready(self) -> None:
        # §5.11 reporting (REP4/REP5) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que
        # `core.events` — jamais un import direct par `apps.reporting`.
        from apps.sales.services.ai_context_registration import register_ai_context
        from apps.sales.services.reports_registration import register_reports

        register_reports()
        # AI2 (assistant contextuel par page/action) : meme patron, registre
        # partage `core.services.ai_context_registry`.
        register_ai_context()
