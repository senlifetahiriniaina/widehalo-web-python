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
        from apps.projects.services.automation_registration import register_actions
        from apps.projects.services.reports_registration import register_reports

        register_actions()
        register_reports()
