from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.projects"
    label = "projects"
    verbose_name = "Gestion de projets"

    # PJ1 : aucun enregistrement `reports_registry`/`automation_registry`
    # a ce stade (zero rapport, zero automatisation construits) —
    # contrairement a `financing`/`feasibility` qui cablent
    # `register_reports()` des leur premiere etape parce qu'un rapport
    # existait deja. Les rapports Gantt/EVM/avancement arrivent a PJ15
    # (`reports_registry`) et les automatisations a PJ11
    # (`automation_registry`) — `ready()` sera complete a ces etapes.
