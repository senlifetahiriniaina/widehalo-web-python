"""L0-3 — declaration des commandes periodiques de `quality`.

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
        "quality.overdue_controls",
        command="run_quality_control_checks",
        module="quality",
        label="Contrôles qualité en retard",
        frequency=FREQUENCY_DAILY,
        hour=6,
        description=(
            "QUA-9. Dédoublonnée depuis L0-1 sur le couple plan/lot : un contrôle en retard le "
            "reste jusqu'à ce qu'il soit fait."
        ),
    )
