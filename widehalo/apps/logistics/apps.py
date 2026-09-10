from django.apps import AppConfig


class LogisticsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.logistics"
    label = "logistics"
    verbose_name = "Logistique"

    def ready(self) -> None:
        # C-3 : declare comment calculer les suites possibles des
        # documents de ce module (registre `core.services.next_steps`).
        # `core` ne depend d'aucun module metier : c'est le module qui
        # se declare, jamais le socle qui l'importe.
        from apps.logistics.services.next_steps_registration import register as register_next_steps

        register_next_steps()

        # §5.11 reporting (REP5) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que
        # `core.events` — jamais un import direct par `apps.reporting`.
        from apps.logistics.services.ai_anomaly_registration import register_ai_anomaly_checks
        from apps.logistics.services.ai_context_registration import register_ai_context
        from apps.logistics.services.reports_registration import register_reports

        register_reports()
        # AI2 (assistant contextuel par page/action) : meme patron, registre
        # partage `core.services.ai_context_registry`.
        register_ai_context()
        # INT2 (participation aux registres IA generiques) : anomalies,
        # meme patron que `helpdesk`/`stocks`.
        register_ai_anomaly_checks()
