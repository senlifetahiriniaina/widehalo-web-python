from django.apps import AppConfig


class MrpConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.mrp"
    label = "mrp"
    verbose_name = "Production"

    def ready(self) -> None:
        # §5.11 reporting (REP5) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que
        # `core.events` — jamais un import direct par `apps.reporting`.
        from apps.mrp.services.automation_registration import (
            register_actions as register_automation_actions,
        )
        from apps.mrp.services.reports_registration import register_reports

        register_reports()
        # AUTO3 (Studio de workflow visuel) : meme patron, registre partage
        # `core.services.automation_registry`.
        register_automation_actions()
