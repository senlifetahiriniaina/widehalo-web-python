from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.projects"
    label = "projects"
    verbose_name = "Gestion de projets"

    # PJ11 : auto-enregistrement des actions dans le registre partage
    # `core.services.automation_registry` (meme patron que `apps.mrp`/
    # `apps.purchase`, chantier Studio de workflow visuel).
    # PJ15 : auto-enregistrement des rapports Gantt/EVM/etat de projet dans
    # le registre partage `core.services.reports_registry` — cf.
    # `apps.projects.services.reports_registration` pour le detail.
    def ready(self) -> None:
        from apps.projects.services.ai_anomaly_registration import register_ai_anomaly_checks
        from apps.projects.services.ai_context_registration import register_ai_context
        from apps.projects.services.automation_registration import register_actions
        from apps.projects.services.reports_registration import register_reports

        register_actions()
        register_reports()
        # AI2 (assistant contextuel par page/action) : meme patron, registre
        # partage `core.services.ai_context_registry`.
        register_ai_context()
        # AI3 (detection d'anomalies cross-modules) : meme patron, registre
        # partage `core.services.anomaly_registry`.
        register_ai_anomaly_checks()
