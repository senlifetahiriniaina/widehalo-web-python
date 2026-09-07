"""FLX-8 — la rédaction des secrets DANS LES JOURNAUX.

**Un formateur, et pas un filtre**, et la nuance est tout ce qui fait
qu'il sert à quelque chose. Un `logging.Filter` voit `record.msg` et
`record.args` ; il ne voit PAS la trace d'exception, qui n'est rendue
qu'au moment du formatage. Or `logger.exception(...)` est précisément la
forme sous laquelle un secret arrive dans un journal — dans le corps de
requête recopié par la bibliothèque HTTP, dans la représentation de
l'objet qui a levé. Un filtre aurait donné l'impression de couvrir la
surface tout en laissant passer sa moitié la plus dangereuse.

Le coût est assumé : la rédaction s'exécute sur CHAQUE enregistrement
formaté. Elle est faite de cinq expressions régulières compilées sur un
texte déjà en mémoire ; c'est négligeable devant l'écriture elle-même, et
un journal est de toute façon écrit à un rythme humain.
"""

from __future__ import annotations

import logging

from apps.core.services.redaction import redact_secrets


class SecretRedactingFormatter(logging.Formatter):
    """Formateur standard, dont la sortie passe par la rédaction.

    Rédige APRÈS formatage, donc message, arguments, trace d'exception et
    pile incluses — c'est l'ensemble de ce qui sera écrit, et c'est la
    seule granularité à laquelle « aucun motif de secret n'apparaît dans
    un journal » se vérifie."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))
