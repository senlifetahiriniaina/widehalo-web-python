"""L0-3 — declaration des commandes periodiques de `bi`.

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
        "bi.diffusions",
        command="run_bi_diffusions",
        module="bi",
        label="Diffusions BI planifiées",
        frequency=FREQUENCY_DAILY,
        hour=6,
        description=(
            "BI-7. Après le rafraîchissement de l'entrepôt (1 h) : diffuser avant lui enverrait "
            "les chiffres de la veille."
        ),
    )
