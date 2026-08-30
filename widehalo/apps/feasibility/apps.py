from django.apps import AppConfig


class FeasibilityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.feasibility"
    label = "feasibility"
    verbose_name = "Etudes de faisabilite"

    def ready(self) -> None:
        # §5.11 reporting (REP5) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que tous
        # les autres modules metier (`strategy`/`financing`) — jamais un
        # import direct par `apps.reporting`.
        from apps.feasibility.services.ai_context_registration import register_ai_context
        from apps.feasibility.services.automation_registration import (
            register_actions as register_automation_actions,
        )
        from apps.feasibility.services.reports_registration import register_reports

        register_reports()
        # AI2 (assistant contextuel par page/action) : meme patron, registre
        # partage `core.services.ai_context_registry`.
        register_ai_context()
        # INT1 (chantier interactivite native inter-modules) : meme patron,
        # registre partage `core.services.automation_registry`.
        register_automation_actions()
