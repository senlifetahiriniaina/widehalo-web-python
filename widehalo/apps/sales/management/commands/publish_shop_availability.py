"""T7 (bloc G, COM-3) — publie la disponibilite a la vente vers la boutique.

Planifiee depuis `apps.sales.services.scheduling_registration` : la
disponibilite change a chaque mouvement de stock et a chaque reservation,
donc elle se republie. C'est ce qui fait de `publish_availability` autre
chose qu'une fonction ecrite pour rien — sans cette commande, elle n'aurait
aucun appelant, et le motif « rien de decoratif » se rejouerait.

**Ce que la commande publie, et le mot qui compte.** `stocks` expose
`get_available_stock_qty`, c'est-a-dire `qty - qty_reserved` sur les
emplacements internes (RG-STK-8). Publier le stock PHYSIQUE reviendrait a
vendre ce qui est deja promis a quelqu'un d'autre — la boutique
accepterait la commande, et c'est a la preparation qu'on decouvrirait
qu'il n'y a rien a expedier.

**Une societe sans raccordement de boutique est ignoree, pas en echec.**
`publish_availability` rend `None` quand aucune liaison active ne sert le
connecteur : c'est l'etat de toute installation qui ne vend pas en ligne,
et faire echouer la passe pour elles empecherait de publier pour les
autres.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.catalog.services.public import list_sellable_variants
from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step
from apps.sales.services.shop_publication import publish_availability


class Command(BaseCommand):
    help = (
        "COM-3 : publie la disponibilite A LA VENTE (reservations deduites) "
        "des articles vendables, vers la boutique raccordee."
    )

    def handle(self, *args, **options) -> None:
        publiees = 0
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                # **`list_sellable_variants` et non toutes les variantes.**
                # Publier une matiere premiere ou un composant interne
                # offrirait a la vente ce qui n'est pas vendable — et
                # `catalog` sait deja repondre a cette question, par sa
                # surface publique (regle de couplage n°1 : jamais
                # `catalog.models` depuis ici, ce que la garde a refuse).
                variant_ids = [vendable["id"] for vendable in list_sellable_variants()]
                if not variant_ids:
                    continue
                accuse = publish_availability(tenant, variant_ids=variant_ids)
                if accuse is None:
                    # Aucune liaison active : cette societe ne vend pas en
                    # ligne. Etat normal, jamais un echec.
                    continue
                publiees += 1
        self.stdout.write(self.style.SUCCESS(f"Disponibilite publiee pour {publiees} societe(s)."))
