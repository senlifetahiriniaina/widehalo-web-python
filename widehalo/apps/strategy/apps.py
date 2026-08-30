from django.apps import AppConfig


class StrategyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.strategy"
    label = "strategy"
    verbose_name = "Strategie et pilotage"

    def ready(self) -> None:
        # §5.11 reporting (REP5) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que tous
        # les autres modules metier — jamais un import direct par
        # `apps.reporting`.
        from apps.strategy.services.ai_context_registration import register_ai_context
        from apps.strategy.services.ai_insight_registration import register_ai_insight_sources
        from apps.strategy.services.reports_registration import register_reports

        register_reports()
        # AI2 (assistant contextuel par page/action) : meme patron, registre
        # partage `core.services.ai_context_registry`.
        register_ai_context()
        # AI5 (insights proactifs automatises) : meme patron, registre
        # partage `core.services.insight_source_registry`.
        register_ai_insight_sources()
