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
        from apps.financing.services.reports_registration import register_reports

        register_reports()
