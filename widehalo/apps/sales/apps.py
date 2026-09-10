from django.apps import AppConfig


class SalesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sales"
    label = "sales"
    verbose_name = "Ventes"

    def ready(self) -> None:
        # C-3 : declare comment calculer les suites possibles des
        # documents de ce module (registre `core.services.next_steps`).
        # `core` ne depend d'aucun module metier : c'est le module qui
        # se declare, jamais le socle qui l'importe.
        from apps.sales.services.next_steps_registration import register as register_next_steps

        register_next_steps()

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
        from apps.sales.services.document_screen_registration import (
            register_document_screens,
        )
        from apps.sales.services.flow_schema_registration import register_outbound_schemas
        from apps.sales.services.reports_registration import register_reports
        from apps.sales.services.scheduling_registration import register_scheduled_commands
        from apps.sales.services.shop_registration import register_shop_subscribers

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
        # T0 (Phase 4, axes A1/A2 et §9.2) : declaration de ce que ce
        # module accepte de laisser sortir — registre partage
        # `core.services.outbound_schemas`. Sans elle, aucune
        # correspondance de champs ne peut designer une piece de ce
        # module : la fermeture est deny-by-default.
        register_outbound_schemas()
        # T7 (bloc G, COM-1) : l'abonne qui fait entrer les commandes de
        # boutique. Le hub publie `flows.inbound_received` ; c'est `sales`
        # qui decide que cela le concerne, jamais l'inverse.
        #
        # Il ingere AU STATUT INITIAL et ne confirme rien : confirmer
        # declenche la qualification d'approvisionnement, donc des
        # mouvements de stock — ce que COM-1 interdit a une commande
        # ingeree. La garde `test_ingested_orders_stay_at_the_initial_
        # state.py` le verifie.
        register_shop_subscribers()
        # T8 (bloc H, CON-1) : ou se voit une piece de ce module, pour que
        # chaque ligne du journal des echanges y renvoie. Le hub ne peut pas
        # le savoir — il ne declare que `core` — c'est donc ce module qui se
        # declare, comme pour ses rapports et ses schemas de sortie.
        register_document_screens()
