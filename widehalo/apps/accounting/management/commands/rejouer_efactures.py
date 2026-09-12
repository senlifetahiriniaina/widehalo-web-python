"""F-1 — la commande d'exploitation qui rejoue la file d'e-factures.

**Pourquoi une commande EN PLUS de l'écran.** L'écran porte la décision
d'ouverture ; la commande porte le rattrapage — après un incident du tiers,
après une coupure, ou depuis un poste d'exploitation sans navigateur. Les
deux appellent le MÊME service : deux chemins qui divergeraient finiraient
par ne pas produire le même résultat.

**Elle n'est PAS déclarée à l'ordonnanceur, et c'est une décision.**
Soumettre des pièces à une administration fiscale sans que personne ne
l'ait demandé n'est pas une tâche de fond — c'est exactement ce que le
cahier encadre par « la confirmation initiale ». Une commande sans entrée
de planification est ici le comportement voulu, pas un oubli ; l'écran est
le déclencheur normal.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.accounting.services.einvoice_replay import replay_pending_submissions
from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step


class Command(BaseCommand):
    help = "Rejoue la file des factures en attente de soumission fiscale."

    def handle(self, *args: Any, **options: Any) -> None:
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                rapport = replay_pending_submissions(tenant)
                self.stdout.write(
                    f"{tenant.code} : {rapport.considered} piece(s) consideree(s), "
                    f"{rapport.queued} mise(s) en file, {rapport.still_pending} encore en attente."
                )
