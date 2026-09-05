from django.apps import AppConfig


class SalesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sales"
    label = "sales"
    verbose_name = "Ventes"

    def ready(self) -> None:
        # L0-3 : declaration des commandes periodiques de ce module
        # (registre `core.services.scheduled_commands`). Declare seulement —
        # l'ecriture des planifications est faite au deploiement par
        # `apps.core.tasks.sync_schedules`.
        # §5.11 reporting (REP4/REP5) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que
        # `core.events` — jamais un import direct par `apps.reporting`.
        from apps.sales.services.ai_anomaly_registration import register_ai_anomaly_checks
        from apps.sales.services.ai_context_registration import register_ai_context
        from apps.sales.services.ai_data_query_registration import register_ai_data_query_tools
        from apps.sales.services.ai_insight_registration import register_ai_insight_sources
        from apps.sales.services.reports_registration import register_reports
        from apps.sales.services.scheduling_registration import register_scheduled_commands

        register_reports()
        # AI2 (assistant contextuel par page/action) : meme patron, registre
        # partage `core.services.ai_context_registry`.
        register_ai_context()
        # AI3 (detection d'anomalies cross-modules) : meme patron, registre
        # partage `core.services.anomaly_registry`.
        register_ai_anomaly_checks()
        # AI5 (insights proactifs automatises) : meme patron, registre
        # partage `core.services.insight_source_registry`.
        register_ai_insight_sources()
        # GW3 (passerelle IA locale d'analyse de donnees) : meme patron,
        # registre partage `core.services.data_query_tool_registry`.
        register_ai_data_query_tools()
        register_scheduled_commands()
