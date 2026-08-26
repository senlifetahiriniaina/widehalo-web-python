from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _apply_rls(sender, **kwargs) -> None:
    from apps.core.management.commands.apply_rls import apply_rls

    apply_rls()


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
    verbose_name = "Socle"

    def ready(self) -> None:
        from apps.core import events  # noqa: F401
        from apps.core.workflows import connect_workflow_signals

        # Pas de filtre `sender` : on veut reappliquer RLS apres la migration
        # de N'IMPORTE QUELLE app (partners, catalog, futurs modules metier),
        # pas seulement core. apply_rls() est idempotent.
        post_migrate.connect(_apply_rls)
        connect_workflow_signals()
