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
        from apps.core.events import subscribe_all
        from apps.flows.adapters import reference
        from apps.flows.services.adapter_registry import register_adapter
        from apps.flows.services.scheduling_registration import register_scheduled_commands
        from apps.flows.services.triggers import dispatch_event_to_triggers

        register_scheduled_commands()

        # S6 : le premier adaptateur, declare ICI et jamais a l'import du
        # module. Un module qui s'enregistrerait tout seul rendrait le
        # registre dependant de l'ordre des imports, et un `import` oublie
        # dans un test suffirait a changer le comportement de la vidange.
        register_adapter(reference.CONNECTOR_CODE, reference.send)

        # FLX-2 (S5) : UN SEUL abonne generique, comme `automation`. Il
        # recoit tout evenement publie et n'agit que sur ceux qu'un
        # `FlwTrigger` actif designe — aucun module metier n'a donc a
        # connaitre `flows` pour qu'une de ses transitions declenche un
        # echange, ce qui est exactement le sens de dependance que
        # `services/public.py` decrit.
        subscribe_all(dispatch_event_to_triggers)
