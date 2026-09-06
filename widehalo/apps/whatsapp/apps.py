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

        # L0-3/WA-7 (L10) : la file d'envoi a enfin un declencheur
        # automatique. Avant ce lot, `apps/whatsapp/` n'avait aucune
        # commande de gestion et le registre d'ordonnancement aucune
        # entree WhatsApp — « repris automatiquement » reposait sur un
        # bouton.
        from apps.whatsapp.services.scheduling_registration import register_scheduled_commands

        register_scheduled_commands()
