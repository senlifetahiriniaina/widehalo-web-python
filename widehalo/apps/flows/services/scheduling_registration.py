"""S3 puis S5 — declaration des commandes periodiques du hub de flux.

Cadence HORAIRE, et le motif est le meme que pour la file WhatsApp :
l'espacement de reessai par defaut de l'axe A5 demarre a cinq minutes, et
un declencheur quotidien rendrait le premier reessai utile vingt-quatre
heures apres l'echec. `FREQUENCY_HOURLY` n'affiche pas d'heure
d'execution — le parametre `hour` est donc omis plutot que renseigne a une
valeur qui ne serait jamais lue.
"""

from __future__ import annotations

from django.conf import settings

from apps.core.services.scheduled_commands import (
    FREQUENCY_HOURLY,
    register_scheduled_command,
)


def register_scheduled_commands() -> None:
    register_scheduled_command(
        "flows.outbound_queue",
        command="run_flows_queue",
        module="flows",
        label="File de sortie du hub de flux",
        frequency=FREQUENCY_HOURLY,
        description=(
            "FLX-3. Vide la file de sortie : envoie les échanges dus, respecte "
            "l'espacement croissant réglé sur chaque liaison, et laisse en file — sans "
            "appel réseau — ceux dont le disjoncteur est ouvert."
        ),
        # §7.6 : la file dédiée aux échanges. Vide par défaut — le cluster
        # partagé, donc le comportement de toutes les autres commandes —
        # tant que l'exploitation n'a pas déployé le worker qui porte ce
        # nom. Lier la commande à un cluster absent l'empêcherait de
        # s'exécuter, en silence.
        cluster=settings.FLOWS_QUEUE_CLUSTER_NAME,
    )
    register_scheduled_command(
        "flows.schedules",
        command="run_flows_schedules",
        module="flows",
        label="Planifications du hub de flux",
        frequency=FREQUENCY_HOURLY,
        description=(
            "Axe A4. Fait naître les échanges des planifications dues et réarme leur "
            "échéance suivante, décalée sur un jour ouvré quand la liaison le demande. "
            "Ne contacte aucun tiers : la file de sortie s'en charge."
        ),
        # Cadence horaire obligatoire, et pour une raison de definition
        # plutot que de confort : `FlwSchedule.FREQUENCY_HOURLY` existe, et
        # un repartiteur quotidien la rendrait inapplicable — une
        # planification horaire ne tournerait qu'une fois par jour.
        cluster=settings.FLOWS_QUEUE_CLUSTER_NAME,
    )
