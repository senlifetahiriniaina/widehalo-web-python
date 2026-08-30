from django.apps import AppConfig


class PresenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.presence"
    label = "presence"
    verbose_name = "Présence et absences"

    def ready(self) -> None:
        # AI2 (assistant contextuel par page/action) : auto-enregistrement
        # dans le registre partage `core.services.ai_context_registry`,
        # meme patron que tous les autres modules metier — jamais un import
        # direct par `apps.ai`.
        from apps.presence.services.ai_context_registration import register_ai_context
        from apps.presence.services.ai_insight_registration import register_ai_insight_sources

        register_ai_context()
        # AI5 (insights proactifs automatises) : meme patron, registre
        # partage `core.services.insight_source_registry`.
        register_ai_insight_sources()
