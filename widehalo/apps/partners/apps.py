from django.apps import AppConfig


class PartnersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.partners"
    label = "partners"
    verbose_name = "Partenaires"

    def ready(self) -> None:
        # AI2 (assistant contextuel par page/action) : auto-enregistrement
        # dans le registre partage `core.services.ai_context_registry`,
        # meme patron que tous les autres modules metier — jamais un import
        # direct par `apps.ai`.
        from apps.partners.services.ai_anomaly_registration import register_ai_anomaly_checks
        from apps.partners.services.ai_context_registration import register_ai_context
        from apps.partners.services.automation_registration import (
            register_actions as register_automation_actions,
        )
        from apps.partners.services.document_screen_registration import (
            register_document_screens,
        )
        from apps.partners.services.scheduling_registration import register_scheduled_commands

        register_ai_context()
        # INT1 (chantier interactivite native inter-modules) : meme patron,
        # registre partage `core.services.automation_registry`.
        register_automation_actions()
        # INT2 (participation aux registres IA generiques) : anomalies,
        # meme patron que `helpdesk`/`stocks`.
        register_ai_anomaly_checks()
        # T3 (OP8) : declaration de la commande periodique de verification
        # des identifiants fiscaux — registre partage
        # `core.services.scheduled_commands`. Declare seulement ; l'ecriture
        # des planifications est faite au deploiement par
        # `apps.core.tasks.sync_schedules`.
        register_scheduled_commands()
        # T8 (bloc H, CON-1) : ou se voit une piece de ce module, pour que
        # chaque ligne du journal des echanges y renvoie. Le hub ne peut pas
        # le savoir — il ne declare que `core` — c'est donc ce module qui se
        # declare, comme pour ses rapports et ses schemas de sortie.
        register_document_screens()
