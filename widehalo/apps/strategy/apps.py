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
        from apps.strategy.services.reports_registration import register_reports

        register_reports()
