"""L0-3 — declaration des commandes periodiques de `purchase`.

Meme patron que les autres registres du depot (`reports_registration`,
`ai_context_registration`...) : l'app declare ce qui lui appartient, `core`
n'a jamais a connaitre les commandes des autres modules. La cadence est une
donnee ; l'ecriture des planifications est faite par
`apps.core.tasks.sync_schedules`, seul autorise a importer `django_q`.
"""

from __future__ import annotations

from apps.core.services.scheduled_commands import (
    FREQUENCY_DAILY,
    FREQUENCY_MONTHLY,
    register_scheduled_command,
)


def register_scheduled_commands() -> None:
    register_scheduled_command(
        "purchase.reordering",
        command="run_purchase_reordering",
        module="purchase",
        label="Propositions de réapprovisionnement",
        frequency=FREQUENCY_DAILY,
        hour=5,
        description=(
            "Idempotente depuis L0-1 : sans cette garde, une proposition ET une demande "
            "d'approbation étaient créées à chaque exécution, jusqu'à la réception réelle des "
            "marchandises."
        ),
    )
    register_scheduled_command(
        "purchase.price_watch",
        command="run_price_watch_checks",
        module="purchase",
        label="Veille prix fournisseurs",
        frequency=FREQUENCY_MONTHLY,
        hour=5,
        description=(
            "PRC3 — mensuelle, cadence des cibles de veille elles-mêmes. Aucun appel réseau tant "
            "qu'aucun fournisseur de prix n'est configuré."
        ),
    )
