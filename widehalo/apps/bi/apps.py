from django.apps import AppConfig


class BiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.bi"
    label = "bi"
    verbose_name = "Business Intelligence"

    def ready(self) -> None:
        # L0-3 : declaration des commandes periodiques de ce module
        # (registre `core.services.scheduled_commands`). Declare seulement —
        # l'ecriture des planifications est faite au deploiement par
        # `apps.core.tasks.sync_schedules`.
        # BI-8 : enregistre le rapport générique qui permet à `apps.
        # reporting` (RptJob/generate_report) d'exporter N'IMPORTE QUEL
        # `BiReport` de façon asynchrone, sans que `bi` ait besoin de son
        # propre modèle de job (cf. docstring `services/export.py`).
        from apps.bi.services.export import REPORT_CODE, render_bi_report_rows
        from apps.bi.services.scheduling_registration import register_scheduled_commands
        from apps.core.services.reports_registry import register_report

        register_report(
            code=REPORT_CODE,
            module="bi",
            label="Rapport BI (auto-généré)",
            permission="bi.view_bireport",
            # Le seul rapport du catalogue dont le propriétaire n'est pas
            # une fonction métier : c'est un PONT, pas un rapport. Il
            # exécute le rapport sémantique que l'utilisateur a lui-même
            # construit (`BiReport`, qui porte SON propre propriétaire et
            # sa propre description) pour le faire passer par le moteur de
            # travaux de fond. Lui attribuer un propriétaire métier
            # laisserait croire qu'une fonction répond de son contenu,
            # alors que son contenu change à chaque appel.
            owner_role="admin",
            description=(
                "Exécute un rapport BI construit par l'utilisateur, pour le sortir en "
                "PDF ou en tableur. Son contenu est celui du rapport sémantique "
                "désigné, jamais une définition figée."
            ),
            render_rows=render_bi_report_rows,
        )
        register_scheduled_commands()
