from django.apps import AppConfig


class StocksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.stocks"
    label = "stocks"
    verbose_name = "Stocks"

    def ready(self) -> None:
        # §5.11 reporting (REP5) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que
        # `core.events` — jamais un import direct par `apps.reporting`.
        from apps.stocks.services.ai_context_registration import register_ai_context
        from apps.stocks.services.reports_registration import register_reports

        register_reports()
        # AI2 (assistant contextuel par page/action) : meme patron, registre
        # partage `core.services.ai_context_registry`.
        register_ai_context()
