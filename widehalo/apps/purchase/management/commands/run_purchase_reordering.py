"""Commande ops (§5.6.2, PU5, RG-PUR-3) : declenche le reapprovisionnement
automatique pour tous les tenants. Mirroir exact de
`apps.sales.management.commands.run_sales_recurrences` (S5, RG-SAL-6) :
meme structure (boucle `Tenant.objects.all()` + `activate_tenant`), meme
absence deliberee de cablage automatique dans `core.tasks.enqueue`/un
`Schedule` de cron — aucun mecanisme de cron n'est encore cable ailleurs
dans le projet pour ce type de tache (meme constat que S5), donc aucun
n'est invente ici : cette commande est destinee a etre invoquee par un
processus ops/humain (cron systeme ou, plus tard, une entree de
planification Django-Q2), jamais auto-enregistree."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.purchase.services.reordering import run_reordering


class Command(BaseCommand):
    help = (
        "RG-PUR-3 : genere les demandes d'achat de reapprovisionnement "
        "automatique (brouillon, jamais soumise/approuvee) pour tous les tenants."
    )

    def handle(self, *args, **options) -> None:
        total_created = 0
        for tenant in Tenant.objects.all():
            with activate_tenant(tenant.id):
                created = run_reordering(tenant)
            total_created += len(created)
            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {len(created)} demande(s) d'achat generee(s)."
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Tenant {tenant.code} : aucune demande generee "
                        "(aucune regle declenchee ou aucun superutilisateur disponible)."
                    )
                )
        self.stdout.write(self.style.SUCCESS(f"Total : {total_created} demande(s) generee(s)."))
