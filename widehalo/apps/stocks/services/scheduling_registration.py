"""L0-3 — declaration des commandes periodiques de `stocks`.

Meme patron que les autres registres du depot (`reports_registration`,
`ai_context_registration`...) : l'app declare ce qui lui appartient, `core`
n'a jamais a connaitre les commandes des autres modules. La cadence est une
donnee ; l'ecriture des planifications est faite par
`apps.core.tasks.sync_schedules`, seul autorise a importer `django_q`.
"""

from __future__ import annotations

from apps.core.services.scheduled_commands import (
    FREQUENCY_DAILY,
    FREQUENCY_WEEKLY,
    register_scheduled_command,
)


def register_scheduled_commands() -> None:
    register_scheduled_command(
        "stocks.expiry_alerts",
        command="run_expiry_alerts",
        module="stocks",
        label="Alertes de péremption",
        frequency=FREQUENCY_DAILY,
        hour=6,
        description=("FOR-15. Dédoublonnée sur le lot depuis L0-1."),
    )
    register_scheduled_command(
        "stocks.expire_reservations",
        command="expire_stock_reservations",
        module="stocks",
        label="Expiration des réservations",
        frequency=FREQUENCY_DAILY,
        hour=2,
        description=("RG-STK-8."),
    )
    register_scheduled_command(
        "stocks.quant_consistency",
        command="check_quant_consistency",
        module="stocks",
        label="Contrôle de cohérence des quants",
        frequency=FREQUENCY_DAILY,
        hour=1,
        description=(
            "STK-2 — le « contrôle nocturne » que le critère exige et qui n'avait aucun "
            "ordonnanceur."
        ),
    )
    register_scheduled_command(
        "stocks.production_consistency",
        command="check_production_consistency",
        module="stocks",
        label="Cohérence de production",
        frequency=FREQUENCY_WEEKLY,
        hour=1,
        description=("RG-STK-6."),
    )
