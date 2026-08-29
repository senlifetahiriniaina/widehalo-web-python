from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.projects"
    label = "projects"
    verbose_name = "Gestion de projets"

    # PJ11 : auto-enregistrement des actions dans le registre partage
    # `core.services.automation_registry` (meme patron que `apps.mrp`/
    # `apps.purchase`, chantier Studio de workflow visuel). Les rapports
    # Gantt/EVM/avancement (`reports_registry`) restent a PJ15 —
    # `register_reports()` sera ajoute a cette etape.
    def ready(self) -> None:
        from apps.projects.services.automation_registration import register_actions

        register_actions()
