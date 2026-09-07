"""Commande ops (S5, axe A4) : fait naître les échanges des planifications
dues.

**Livrée avec le répartiteur, et non « au sprint qui en aura besoin ».**
La leçon est écrite deux sprints plus tôt dans ce dépôt : la file de sortie
et son espacement de réessai existaient depuis S3, et c'est
`run_flows_queue` — livrée en même temps — qui les rend vivantes. Une
planification sans ordonnanceur est un `next_run_at` que rien ne lit,
exactement l'état dans lequel `FlwSchedule` se trouvait avant ce sprint.

**Ce qu'elle fait, sans embellir.** Elle met en file. Elle n'appelle aucun
tiers : c'est `run_flows_queue` qui émet, avec le disjoncteur et
l'espacement de réessai. Un répartiteur qui émettrait lui-même les
contournerait tous les deux.

Cadence HORAIRE, parce que c'est la maille la plus fine que
`FlwSchedule.FREQUENCY_HOURLY` propose : une cadence quotidienne rendrait
inapplicable la moitié des fréquences que le modèle déclare.

Idempotente : une passe sans planification due n'écrit rien. Deux passes
successives ne créent pas deux échanges — la première réarme `next_run_at`
sur l'échéance suivante.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.flows.services.scheduling import run_due_schedules


class Command(BaseCommand):
    help = (
        "Axe A4 : met en file les échanges des planifications dues, en respectant "
        "le calendrier des jours ouvrés de chaque société."
    )

    def handle(self, *args, **options) -> None:
        totaux = run_due_schedules()
        self.stdout.write(
            self.style.SUCCESS(
                f"Planifications traitées : {totaux['queued']} échange(s) mis en file, "
                f"{totaux['failed']} société(s) en échec."
            )
        )
