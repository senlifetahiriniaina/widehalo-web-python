from django.apps import AppConfig


class PresenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.presence"
    label = "presence"
    verbose_name = "Présence et absences"

    def ready(self) -> None:
        # L0-3 : declaration des commandes periodiques de ce module
        # (registre `core.services.scheduled_commands`). Declare seulement —
        # l'ecriture des planifications est faite au deploiement par
        # `apps.core.tasks.sync_schedules`.
        # AI2 (assistant contextuel par page/action) : auto-enregistrement
        # dans le registre partage `core.services.ai_context_registry`,
        # meme patron que tous les autres modules metier — jamais un import
        # direct par `apps.ai`.
        from apps.presence.services.ai_context_registration import register_ai_context
        from apps.presence.services.ai_insight_registration import register_ai_insight_sources
        from apps.presence.services.scheduling_registration import register_scheduled_commands

        register_ai_context()
        # AI5 (insights proactifs automatises) : meme patron, registre
        # partage `core.services.insight_source_registry`.
        register_ai_insight_sources()
        register_scheduled_commands()
