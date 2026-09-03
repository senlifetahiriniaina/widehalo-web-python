from django.apps import AppConfig


class PayrollConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.payroll"
    label = "payroll"
    verbose_name = "Paie"

    def ready(self) -> None:
        # §5.11 reporting (REP4) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que
        # `core.events` — jamais un import direct par `apps.reporting`.
        from apps.payroll.services.ai_context_registration import register_ai_context
        from apps.payroll.services.chatter_registration import register_chatter_guards
        from apps.payroll.services.reports_registration import register_reports

        register_reports()
        # AI2 (assistant contextuel par page/action) : meme patron, registre
        # partage `core.services.ai_context_registry`.
        register_ai_context()
        # Gap revision complete Sprints 0-9 : garde chatter RG-PAY-9, meme
        # patron, registre partage `core.services.chatter_guard_registry`.
        register_chatter_guards()
