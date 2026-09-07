"""Calendrier national de référence — les DATES non ouvrées d'une société.

**Pourquoi dans `core` et plus dans `forecast`.** Un jour férié malgache
n'est pas une donnée de prévision : c'est une donnée de référence, au même
titre que `CountryDefaultsProfile` qui vit déjà ici. Il se trouve
simplement que le premier module à en avoir eu besoin (FOR-5) l'a déclaré
chez lui.

Le déplacement est devenu nécessaire à la planification des flux (axe A4 :
une planification « adossée au calendrier malgache »). `flows` ne dépend
que de `core` ; `forecast` dépend de sept modules. Faire dépendre le socle
de connectivité du module de prévision pour lire une liste de dates aurait
inversé la hiérarchie, alors que la règle de couplage n°1 existe pour
l'empêcher. La table est renommée en place (`ALTER TABLE … RENAME`) :
aucune ligne ne bouge, et `forecast` relit le calendrier depuis `core`, ce
qui ALLÈGE son couplage au lieu d'alourdir celui de `flows`.

**Ce que cette table ne dit pas.** Elle dit qu'une date n'est pas ouvrée.
Elle ne dit rien du TAUX auquel un jour férié travaillé se paie — c'est une
information de paie, portée séparément par
`apps/presence/services/calendar.py` (`RegulatoryParameter`, code
`presence.public_holiday`). Les deux ne font pas double emploi : l'une
donne les dates, l'autre une majoration. Voir `docs/planning/` pour le
constat mesuré sur ce second calendrier.
"""

from __future__ import annotations

from django.db import models

from apps.core.models.base import BaseModel


class Holiday(BaseModel):
    """Jour férié (FOR-5 : « calendrier applique jours ouvrés/fériés
    malgaches lus en table de référence ; un test vérifie qu'aucune date
    fériée n'est écrite dans le code »).

    Un jour ouvré = ni samedi/dimanche ni ligne `Holiday`. Pas de table
    « tous les jours » : seules les EXCEPTIONS sont stockées."""

    date = models.DateField()
    name = models.CharField(max_length=120)

    class Meta:
        db_table = "core_holiday"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "date"], name="uniq_core_holiday_date")
        ]
        ordering = ["date"]

    def __str__(self) -> str:
        return f"{self.date.isoformat()} — {self.name}"
