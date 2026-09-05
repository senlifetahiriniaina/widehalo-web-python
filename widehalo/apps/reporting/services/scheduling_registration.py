"""L0-3 — declaration des commandes periodiques de `reporting`.

Meme patron que les autres registres du depot (`reports_registration`,
`ai_context_registration`...) : l'app declare ce qui lui appartient, `core`
n'a jamais a connaitre les commandes des autres modules. La cadence est une
donnee ; l'ecriture des planifications est faite par
`apps.core.tasks.sync_schedules`, seul autorise a importer `django_q`.
"""

from __future__ import annotations

from apps.core.services.scheduled_commands import (
    FREQUENCY_DAILY,
    register_scheduled_command,
)


def register_scheduled_commands() -> None:
    register_scheduled_command(
        "reporting.schedules",
        command="run_report_schedules",
        module="reporting",
        label="Rapports planifiés",
        frequency=FREQUENCY_DAILY,
        hour=6,
        description=("RPT-7."),
    )
    register_scheduled_command(
        "reporting.purge_expired_jobs",
        command="purge_expired_report_jobs",
        module="reporting",
        label="Purge des travaux de rapport",
        frequency=FREQUENCY_DAILY,
        hour=5,
        description=("RPT-6 — rétention de 7 jours."),
    )
