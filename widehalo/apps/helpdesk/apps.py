from django.apps import AppConfig


class HelpdeskConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.helpdesk"
    label = "helpdesk"
    verbose_name = "Support et suivi operationnel"

    def ready(self) -> None:
        # L0-3 : declaration des commandes periodiques de ce module
        # (registre `core.services.scheduled_commands`). Declare seulement —
        # l'ecriture des planifications est faite au deploiement par
        # `apps.core.tasks.sync_schedules`.
        # HD5 (cf. plan section « Module `helpdesk` » -> HD5) : integration
        # IA/automatisation transversale, meme patron exact que
        # `apps.purchase.apps.PurchaseConfig.ready()` — 6 auto-enregistrements
        # dans les registres partages `core`, aucun import direct par
        # `apps.ai`/`apps.automation` d'un service `helpdesk`.
        from apps.helpdesk.services.ai_advisor_registration import register_ai_advisor_rules
        from apps.helpdesk.services.ai_anomaly_registration import register_ai_anomaly_checks
        from apps.helpdesk.services.ai_context_registration import register_ai_context
        from apps.helpdesk.services.ai_data_query_registration import (
            register_ai_data_query_tools,
        )
        from apps.helpdesk.services.ai_insight_registration import register_ai_insight_sources
        from apps.helpdesk.services.automation_registration import (
            register_actions as register_automation_actions,
        )
        from apps.helpdesk.services.scheduling_registration import register_scheduled_commands

        # AUTO3 (Studio de workflow visuel) — « connexion native aux
        # operations » concrete, cf. `automation_registration.py`.
        register_automation_actions()
        # AI2 (assistant contextuel par page/action).
        register_ai_context()
        # AI3 (detection d'anomalies cross-modules).
        register_ai_anomaly_checks()
        # AI5 (insights proactifs automatises).
        register_ai_insight_sources()
        # AI7 (advisor d'actions next-best-action).
        register_ai_advisor_rules()
        # GW3 (passerelle IA locale d'analyse de donnees).
        register_ai_data_query_tools()
        register_scheduled_commands()
