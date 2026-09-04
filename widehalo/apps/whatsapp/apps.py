from django.apps import AppConfig


class WhatsappConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.whatsapp"
    label = "whatsapp"
    verbose_name = "WhatsApp Business"

    def ready(self) -> None:
        # WA-9 (cahier Phase 2 §13.4) : integration en lecture seule aux
        # outils IA (GW3, meme patron exact que `apps.helpdesk.services.
        # ai_data_query_registration`) — aucun import direct par `apps.ai`.
        from apps.whatsapp.services.ai_data_query_registration import (
            register_ai_data_query_tools,
        )

        register_ai_data_query_tools()
