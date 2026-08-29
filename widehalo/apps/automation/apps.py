from django.apps import AppConfig


class AutomationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.automation"
    label = "automation"
    verbose_name = "Studio de workflow visuel"

    def ready(self) -> None:
        from apps.automation.services.dispatch import dispatch_event_to_flows
        from apps.core.events import subscribe_all

        # AUTO4 : UN SEUL abonne generique enregistre ici (cf. plan) — reçoit
        # tout evenement publie par n'importe quel module et dispatche vers
        # les `AutoFlow` actifs concernes, sans qu'aucun module n'ait besoin
        # de coder un `@subscribe(event_type)` a l'avance pour le studio.
        subscribe_all(dispatch_event_to_flows)
