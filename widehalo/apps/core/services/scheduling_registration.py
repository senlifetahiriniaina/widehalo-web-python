"""L0-3 — declaration des commandes periodiques de `core`.

Meme patron que les autres registres du depot (`reports_registration`,
`ai_context_registration`...) : l'app declare ce qui lui appartient, `core`
n'a jamais a connaitre les commandes des autres modules. La cadence est une
donnee ; l'ecriture des planifications est faite par
`apps.core.tasks.sync_schedules`, seul autorise a importer `django_q`.
"""

from __future__ import annotations

from apps.core.services.scheduled_commands import (
    FREQUENCY_DAILY,
    FREQUENCY_HOURLY,
    register_scheduled_command,
)


def register_scheduled_commands() -> None:
    register_scheduled_command(
        "core.grouped_notification_emails",
        command="send_grouped_notification_emails",
        module="core",
        label="Résumé horaire des notifications",
        frequency=FREQUENCY_HOURLY,
        hour=0,
        description=(
            "Cadence IMPOSÉE, pas choisie : la fenêtre du résumé est `now − 1 h − "
            "GROUPING_WINDOW`. Planifiée moins souvent qu'à l'heure, elle laisse des "
            "notifications hors fenêtre, jamais envoyées."
        ),
    )
    register_scheduled_command(
        "core.tenant_backups",
        command="run_tenant_backups",
        module="core",
        label="Sauvegardes de tenant",
        frequency=FREQUENCY_DAILY,
        hour=3,
        description=(
            "La planification dont l'absence ne se découvre que le jour où l'on en a besoin."
        ),
    )
    register_scheduled_command(
        "core.purge_expired_sandboxes",
        command="purge_expired_sandboxes",
        module="core",
        label="Purge des bacs à sable expirés",
        frequency=FREQUENCY_DAILY,
        hour=5,
    )
