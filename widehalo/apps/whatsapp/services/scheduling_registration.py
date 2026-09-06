"""L0-3 — declaration des commandes periodiques de `whatsapp`.

Meme patron que les autres registres du depot : l'app declare ce qui lui
appartient, `core` n'a jamais a connaitre les commandes des autres modules.

Cadence HORAIRE, et non quotidienne comme la plupart des commandes de ce
depot : la file WhatsApp ne porte pas un traitement de fond mais des
messages qu'une personne attend. Un backoff de reprise qui commence a
5 minutes (`_RETRY_BACKOFF`) serait sans objet derriere un declencheur
quotidien — le premier delai utile serait de vingt-quatre heures. C'est
aussi la seule cadence du registre pour laquelle l'heure d'execution n'a
pas de sens, `FREQUENCY_HOURLY` ne l'affichant pas (cf. `ScheduledCommand.
cadence`).
"""

from __future__ import annotations

from apps.core.services.scheduled_commands import (
    FREQUENCY_HOURLY,
    register_scheduled_command,
)


def register_scheduled_commands() -> None:
    register_scheduled_command(
        "whatsapp.outbound_queue",
        command="run_whatsapp_queue",
        module="whatsapp",
        label="File d'envoi WhatsApp",
        frequency=FREQUENCY_HOURLY,
        description=(
            "WA-7. Vide la file des messages en attente et relance ceux en échec, en "
            "respectant le backoff 5 min / 30 min / 2 h. C'est le déclencheur automatique "
            "qui manquait : la reprise n'avait que deux appelants, un endpoint et un bouton."
        ),
    )
