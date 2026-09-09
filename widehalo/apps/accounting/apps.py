from django.apps import AppConfig


class AccountingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounting"
    label = "accounting"
    verbose_name = "Comptabilite"

    def ready(self) -> None:
        # §5.11 reporting (REP4/REP5) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que
        # `core.events` — jamais un import direct par `apps.reporting`.
        from apps.accounting.services.ai_anomaly_registration import register_ai_anomaly_checks
        from apps.accounting.services.ai_context_registration import register_ai_context
        from apps.accounting.services.einvoice_registration import (
            register_einvoice_subscribers,
        )
        from apps.accounting.services.flow_schema_registration import (
            register_outbound_schemas,
        )
        from apps.accounting.services.payment_registration import (
            register_payment_subscribers,
        )
        from apps.accounting.services.reports_registration import register_reports

        register_reports()
        # AI2 (assistant contextuel par page/action) : meme patron, registre
        # partage `core.services.ai_context_registry`.
        register_ai_context()
        # AI3 (detection d'anomalies cross-modules) : meme patron, registre
        # partage `core.services.anomaly_registry`.
        register_ai_anomaly_checks()
        # T0 (Phase 4, axes A1/A2 et §9.2) : declaration de ce que ce
        # module accepte de laisser sortir — registre partage
        # `core.services.outbound_schemas`. Sans elle, aucune
        # correspondance de champs ne peut designer une piece de ce
        # module : la fermeture est deny-by-default.
        register_outbound_schemas()
        # T4 (bloc C, EFA-1) : « une facture validee produit un document
        # structure ». L'abonnement passe par le bus plutot que par un
        # appel dans `validate_invoice` — l'evenement est persiste dans la
        # meme transaction que la validation et distribue APRES commit,
        # de sorte qu'un defaut du bloc C ne peut jamais mettre en peril
        # une transition comptable (FLX-2).
        register_einvoice_subscribers()
        # T5 (bloc D, PAY-2) : l'abonne qui relie le point d'entree entrant
        # au moteur de reglement. Sans lui, une notification authentique
        # arrivait, etait tracee, et ne produisait rien — le hub publie,
        # mais personne n'ecoutait.
        register_payment_subscribers()
