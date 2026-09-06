from django.apps import AppConfig


class FlowsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.flows"
    label = "flows"
    verbose_name = "Hub de flux"

    def ready(self) -> None:
        # Import differe : `apps.py::ready()` s'execute pendant le
        # chargement des applications, et un import de module de service au
        # niveau du fichier creerait un cycle avec les modeles. Meme patron
        # que les douze autres modules qui declarent une commande periodique.
        from apps.flows.services.scheduling_registration import register_scheduled_commands

        register_scheduled_commands()
