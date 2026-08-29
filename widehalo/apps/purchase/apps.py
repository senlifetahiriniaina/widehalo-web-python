from django.apps import AppConfig


class PurchaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.purchase"
    label = "purchase"
    verbose_name = "Achats"

    def ready(self) -> None:
        # §5.11 reporting (REP5) : auto-enregistrement dans le registre
        # partage `core.services.reports_registry`, meme patron que
        # `core.events` — jamais un import direct par `apps.reporting`.
        from apps.purchase.services.reports_registration import register_reports

        register_reports()
