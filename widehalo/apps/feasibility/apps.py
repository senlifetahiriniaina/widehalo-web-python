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
        from apps.feasibility.services.reports_registration import register_reports

        register_reports()
