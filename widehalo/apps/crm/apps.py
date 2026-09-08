from django.apps import AppConfig


class CrmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.crm"
    label = "crm"
    verbose_name = "Relation commerciale"

    def ready(self) -> None:
        # §5.11 reporting (REP5) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que
        # `core.events` — jamais un import direct par `apps.reporting`.
        from apps.crm.services.ai_advisor_registration import register_ai_advisor_rules
        from apps.crm.services.ai_anomaly_registration import register_ai_anomaly_checks
        from apps.crm.services.ai_context_registration import register_ai_context
        from apps.crm.services.ai_insight_registration import register_ai_insight_sources
        from apps.crm.services.automation_registration import (
            register_actions as register_automation_actions,
        )
        from apps.crm.services.chatter_registration import register_chatter_guards
        from apps.crm.services.flow_schema_registration import register_outbound_schemas
        from apps.crm.services.reports_registration import register_reports

        register_reports()
        # AI2 (assistant contextuel par page/action) : meme patron, registre
        # partage `core.services.ai_context_registry`.
        register_ai_context()
        # INT1 (chantier interactivite native inter-modules) : meme patron,
        # registre partage `core.services.automation_registry`.
        register_automation_actions()
        # INT2 (participation aux registres IA generiques) : anomalies,
        # insights et advisor, meme patron que `helpdesk`/`purchase`.
        register_ai_anomaly_checks()
        register_ai_insight_sources()
        register_ai_advisor_rules()
        # L4 (CRM-1) : garde de perimetre du chatter. Sans elle, le repli
        # par defaut de `core.views.chatter` est la permission de MODELE
        # `crm.view_crmlead`, que tout commercial porte — le fil de
        # discussion de l'opportunite d'un collegue serait lisible et
        # ecrivable, rouvrant la faille refermee aux bloquants (4/4).
        register_chatter_guards()
        # T0 (Phase 4, axes A1/A2 et §9.2) : declaration de ce que ce
        # module accepte de laisser sortir — registre partage
        # `core.services.outbound_schemas`. Sans elle, aucune
        # correspondance de champs ne peut designer une piece de ce
        # module : la fermeture est deny-by-default.
        register_outbound_schemas()
