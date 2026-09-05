"""Commande ops (§5.6.2, PU5, RG-PUR-3) : declenche le reapprovisionnement
automatique pour tous les tenants.

Meme structure que `run_sales_recurrences` (S5, RG-SAL-6) : boucle
`Tenant.objects.all()` + `tenant_step`. Planifiee depuis L0-3 : la cadence
(quotidienne, 05h) est declaree dans
`apps.purchase.services.scheduling_registration` et appliquee a
l'ordonnanceur par `manage.py sync_scheduled_commands`.

La deduplication de L0-1 est le prealable de cette planification : sans elle,
chaque passage recreait une proposition et une demande d'approbation tant que
la couverture restait sous le seuil, donc jusqu'a reception reelle des
marchandises.

Bloc F, F2 (FOR-12/FOR-13) : depuis ce sprint, `run_reordering` ne genere
plus directement de demande d'achat — elle genere une
`PurReorderingProposal` EN ATTENTE, qui n'est transformee en vraie
`PurRequisition` qu'apres acceptation explicite (cf.
`services.reordering.decide_reordering_proposal`). Le libelle de cette
commande est mis a jour en consequence : "proposition(s) generee(s)",
plus "demande(s) d'achat generee(s)"."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step
from apps.purchase.services.reordering import run_reordering


class Command(BaseCommand):
    help = (
        "RG-PUR-3 : genere des propositions de reapprovisionnement "
        "(en attente d'acceptation/rejet explicite) pour tous les tenants."
    )

    def handle(self, *args, **options) -> None:
        total_created = 0
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                created = run_reordering(tenant)
            total_created += len(created)
            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {len(created)} proposition(s) de "
                        "reapprovisionnement generee(s), en attente de decision."
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Tenant {tenant.code} : aucune proposition generee "
                        "(aucune regle declenchee ou aucun superutilisateur disponible)."
                    )
                )
        self.stdout.write(self.style.SUCCESS(f"Total : {total_created} proposition(s) generee(s)."))
