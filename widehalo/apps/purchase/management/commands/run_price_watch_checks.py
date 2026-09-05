"""Commande ops (PRC3, chantier « veille prix fournisseurs Chine/Europe »
— cf. plan) : declenche la verification de veille prix pour tous les
tenants. Meme structure que `run_purchase_reordering` (PU5, RG-PUR-3) : boucle
`Tenant.objects.all()` + `tenant_step`. Planifiee depuis L0-3 : la cadence
(mensuelle, 05h) est declaree dans
`apps.purchase.services.scheduling_registration` et appliquee a
l'ordonnanceur par `manage.py sync_scheduled_commands`.

**Rappel de la reserve de securite** (cf. `apps.purchase.services.
price_watch` pour le detail complet) : tant qu'aucun connecteur reel n'est
configure via `settings.PRICE_WATCH_PROVIDERS`, cette commande ne
declenche AUCUN appel reseau — chaque releve cree est un `PrcPriceSnapshot`
`is_stub=True` sans prix, journalise comme tel."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step
from apps.purchase.services.price_watch import run_price_watch_checks


class Command(BaseCommand):
    help = (
        "PRC3 : verifie les cibles de veille prix fournisseurs echues "
        "(mensuel/trimestriel) pour tous les tenants et journalise les ecarts."
    )

    def handle(self, *args, **options) -> None:
        total_checked = 0
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                results = run_price_watch_checks(tenant)
            total_checked += len(results)
            if results:
                deviations = [r for r in results if r["deviation_pct"] is not None]
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {len(results)} cible(s) verifiee(s), "
                        f"{len(deviations)} ecart(s) notable(s)."
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"Tenant {tenant.code} : aucune cible echue a verifier.")
                )
        self.stdout.write(self.style.SUCCESS(f"Total : {total_checked} cible(s) verifiee(s)."))
