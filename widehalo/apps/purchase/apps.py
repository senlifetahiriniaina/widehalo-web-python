from django.apps import AppConfig


class PurchaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.purchase"
    label = "purchase"
    verbose_name = "Achats"

    def ready(self) -> None:
        # L0-3 : declaration des commandes periodiques de ce module
        # (registre `core.services.scheduled_commands`). Declare seulement —
        # l'ecriture des planifications est faite au deploiement par
        # `apps.core.tasks.sync_schedules`.
        # §5.11 reporting (REP5) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que
        # `core.events` — jamais un import direct par `apps.reporting`.
        from apps.purchase.services.ai_advisor_registration import register_advisor_rules
        from apps.purchase.services.ai_context_registration import register_ai_context
        from apps.purchase.services.ai_data_query_registration import (
            register_ai_data_query_tools,
        )
        from apps.purchase.services.automation_registration import (
            register_actions as register_automation_actions,
        )
        from apps.purchase.services.reports_registration import register_reports
        from apps.purchase.services.scheduling_registration import register_scheduled_commands

        register_reports()
        # AUTO3 (Studio de workflow visuel) : meme patron, registre partage
        # `core.services.automation_registry`.
        register_automation_actions()
        # AI2 (assistant contextuel par page/action) : meme patron, registre
        # partage `core.services.ai_context_registry`.
        register_ai_context()
        # AI7 (advisor d'actions) : meme patron, registre partage
        # `core.services.advisor_rule_registry`.
        register_advisor_rules()
        # INT2 (participation aux registres IA generiques) : passerelle de
        # requetes de donnees (GW3), meme patron que `helpdesk`/`sales`.
        register_ai_data_query_tools()
        register_scheduled_commands()
