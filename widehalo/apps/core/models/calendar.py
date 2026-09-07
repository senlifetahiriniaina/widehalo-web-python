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

**Source UNIQUE des dates chômées.** Il y en avait trois. Les deux autres
sont supprimées : `CountryDefaultsProfile.holidays` (aucun lecteur, aucun
écrivain) et `apps/presence/services/calendar.py`, qui portait en plus une
valeur fausse — un férié travaillé y valait 150 %, là où la paie applique
2,00, soit 200 %.

**Ce que cette table ne dit pas, et où c'est dit.** Elle dit qu'une date
n'est pas ouvrée. Le TAUX auquel un férié travaillé se paie vit là où il
est lu : `payroll.overtime_multipliers["ferie"] = 2.00` — une majoration de
100 %, confirmée par le commanditaire. Une seule vérité par question.
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
