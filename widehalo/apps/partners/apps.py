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

        register_ai_context()
        # INT1 (chantier interactivite native inter-modules) : meme patron,
        # registre partage `core.services.automation_registry`.
        register_automation_actions()
        # INT2 (participation aux registres IA generiques) : anomalies,
        # meme patron que `helpdesk`/`stocks`.
        register_ai_anomaly_checks()
