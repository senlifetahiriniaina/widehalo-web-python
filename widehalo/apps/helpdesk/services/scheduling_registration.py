"""L0-3 — declaration des commandes periodiques de `helpdesk`.

Meme patron que les autres registres du depot (`reports_registration`,
`ai_context_registration`...) : l'app declare ce qui lui appartient, `core`
n'a jamais a connaitre les commandes des autres modules. La cadence est une
donnee ; l'ecriture des planifications est faite par
`apps.core.tasks.sync_schedules`, seul autorise a importer `django_q`.
"""

from __future__ import annotations

from apps.core.services.scheduled_commands import (
    FREQUENCY_HOURLY,
    register_scheduled_command,
)


def register_scheduled_commands() -> None:
    register_scheduled_command(
        "helpdesk.sla_checks",
        command="run_helpdesk_sla_checks",
        module="helpdesk",
        label="Contrôle des SLA",
        frequency=FREQUENCY_HOURLY,
        hour=0,
        description=(
            "HD2 — horaire : un SLA s'exprime en minutes, le contrôler une fois par jour le "
            "rendrait décoratif."
        ),
    )
