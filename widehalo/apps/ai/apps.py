from django.apps import AppConfig


class AiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
    label = "ai"
    verbose_name = "Intelligence artificielle"

    def ready(self) -> None:
        # L0-3 : declaration des commandes periodiques de ce module
        # (registre `core.services.scheduled_commands`). Declare seulement —
        # l'ecriture des planifications est faite au deploiement par
        # `apps.core.tasks.sync_schedules`.
        from apps.ai.services.scheduling_registration import register_scheduled_commands

        # AI1 : `ai` ne fournit lui-meme aucune guidance contextuelle ni
        # verification d'anomalie (ce sont les AUTRES modules qui
        # s'enregistrent dans les registres `core`, cf. module.py) — rien a
        # enregistrer ici pour l'instant.
        pass
        register_scheduled_commands()
