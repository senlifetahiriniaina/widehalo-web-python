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
            render_rows=render_bi_report_rows,
        )
        register_scheduled_commands()
