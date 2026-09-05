"""L0-3 — declaration des commandes periodiques de `analytics`.

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
        "analytics.warehouse_refresh",
        command="run_analytics_refresh",
        module="analytics",
        label="Rafraîchissement de l'entrepôt",
        frequency=FREQUENCY_DAILY,
        hour=1,
        description=(
            "Le traitement dont dépend tout le reste de la Phase 2 : sans lui, BI, Forecast et "
            "Strategy restituent des tableaux vides. Placé en premier de la nuit, les diffusions "
            "BI le suivant à 6 h."
        ),
    )
