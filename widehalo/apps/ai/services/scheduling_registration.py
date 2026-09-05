"""L0-3 — declaration des commandes periodiques de `ai`.

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
        "ai.anomaly_checks",
        command="run_ai_anomaly_checks",
        module="ai",
        label="Détection d'anomalies",
        frequency=FREQUENCY_DAILY,
        hour=4,
        description=(
            "AI3 — anomalies transverses. Dédoublonnée sur 7 jours depuis L0-1 : sans cela, la "
            "même anomalie était recréée chaque nuit, avec un appel au modèle de langage en "
            "sévérité haute."
        ),
    )
    register_scheduled_command(
        "ai.insights",
        command="generate_ai_insights",
        module="ai",
        label="Insights proactifs",
        frequency=FREQUENCY_WEEKLY,
        hour=4,
        description=(
            "AI5 — hebdomadaire et non quotidienne : un insight de synthèse coûte un appel au "
            "modèle, et un insight répété chaque jour cesse d'être lu."
        ),
    )
