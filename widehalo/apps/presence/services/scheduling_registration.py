"""L0-3 — declaration des commandes periodiques de `presence`.

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
        "presence.maintenance",
        command="run_presence_maintenance",
        module="presence",
        label="Maintenance présence",
        frequency=FREQUENCY_DAILY,
        hour=2,
        description=(
            "PR6 — purge de géolocalisation à 30 jours, bascule des absences injustifiées, "
            "alertes de documents."
        ),
    )
