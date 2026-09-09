"""L0-3 — declaration des commandes periodiques de `sales`.

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
        "sales.recurrences",
        command="run_sales_recurrences",
        module="sales",
        label="Commandes récurrentes",
        frequency=FREQUENCY_DAILY,
        hour=5,
        description=("RG-SAL-6 — génère les commandes échues en brouillon, jamais validées."),
    )
    # T7 (bloc G, COM-3) : « la publication de disponibilite reflete le
    # stock DISPONIBLE A LA VENTE, reservations deduites ». Horaire et non
    # quotidienne : une disponibilite publiee le matin et fausse a midi
    # ferait vendre ce qui est deja promis — le defaut que le critere
    # existe pour empecher.
    register_scheduled_command(
        "sales.shop_availability",
        command="publish_shop_availability",
        module="sales",
        label="Disponibilité publiée en boutique",
        frequency=FREQUENCY_HOURLY,
        description=(
            "COM-3 — publie `qty - qty_reserved` (RG-STK-8), jamais le stock "
            "physique : publier le physique vendrait ce qui est déjà promis."
        ),
    )
