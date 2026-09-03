from django.apps import AppConfig


class BiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.bi"
    label = "bi"
    verbose_name = "Business Intelligence"

    def ready(self) -> None:
        # BI-8 : enregistre le rapport générique qui permet à `apps.
        # reporting` (RptJob/generate_report) d'exporter N'IMPORTE QUEL
        # `BiReport` de façon asynchrone, sans que `bi` ait besoin de son
        # propre modèle de job (cf. docstring `services/export.py`).
        from apps.core.services.reports_registry import register_report

        from apps.bi.services.export import REPORT_CODE, render_bi_report_rows

        register_report(
            code=REPORT_CODE,
            module="bi",
            label="Rapport BI (auto-généré)",
            permission="bi.view_bireport",
            render_rows=render_bi_report_rows,
        )
