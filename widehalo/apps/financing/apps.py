from django.apps import AppConfig


class FinancingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.financing"
    label = "financing"
    verbose_name = "Financement bancaire PME"

    def ready(self) -> None:
        # §5.11 reporting (REP5) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que tous
        # les autres modules metier — jamais un import direct par
        # `apps.reporting`. Cable a partir de FIN4 (cf. `services/
        # reports_registration.py`, meme sequencement que `strategy` —
        # STRATEGY-BP n'a ete cable qu'a STR3, pas des STR1).
        from apps.financing.services.ai_advisor_registration import register_ai_advisor_rules
        from apps.financing.services.ai_context_registration import register_ai_context
        from apps.financing.services.reports_registration import register_reports

        register_reports()
        # AI2 (assistant contextuel par page/action) : meme patron, registre
        # partage `core.services.ai_context_registry`.
        register_ai_context()
        # INT2 (participation aux registres IA generiques) : advisor,
        # meme patron que `helpdesk`/`purchase`.
        register_ai_advisor_rules()
