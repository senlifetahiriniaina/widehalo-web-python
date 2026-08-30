from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
    label = "catalog"
    verbose_name = "Catalogue"

    def ready(self) -> None:
        # AI2 (assistant contextuel par page/action) : auto-enregistrement
        # dans le registre partage `core.services.ai_context_registry`,
        # meme patron que tous les autres modules metier — jamais un import
        # direct par `apps.ai`.
        from apps.catalog.services.ai_context_registration import register_ai_context

        register_ai_context()
