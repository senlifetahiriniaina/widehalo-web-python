"""T3 — declaration de la commande periodique de `partners`.

Meme patron que les autres registres du depot (`reports_registration`,
`scheduling_registration` de `sales`...) : l'app declare ce qui lui
appartient, `core` n'a jamais a connaitre les commandes des autres modules.
La cadence est une donnee ; l'ecriture des planifications est faite par
`apps.core.tasks.sync_schedules`, seul autorise a importer `django_q`.
"""

from __future__ import annotations

from apps.core.services.scheduled_commands import (
    FREQUENCY_DAILY,
    register_scheduled_command,
)


def register_scheduled_commands() -> None:
    register_scheduled_command(
        "partners.fiscal_verification",
        command="verify_fiscal_identifiers",
        module="partners",
        label="Vérification des identifiants fiscaux",
        frequency=FREQUENCY_DAILY,
        hour=4,
        description=(
            "OP8 — demande la vérification des identifiants fiscaux dont la "
            "réponse manque ou a expiré, et relit les verdicts arrivés. La "
            "valeur saisie reste autoritative : le référentiel annote, il ne "
            "corrige pas."
        ),
    )
