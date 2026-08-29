from django.apps import AppConfig


class AutomationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.automation"
    label = "automation"
    verbose_name = "Studio de workflow visuel"

    def ready(self) -> None:
        # AUTO4 branchera ici l'abonnement generique `core.events.
        # subscribe_all(dispatch_event_to_flows)` — squelette AUTO3
        # volontairement sans effet de bord au demarrage (models +
        # registre d'actions uniquement a ce stade).
        pass
