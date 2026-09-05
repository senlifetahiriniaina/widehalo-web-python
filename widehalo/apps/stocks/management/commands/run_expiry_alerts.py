"""Commande ops (FOR-15, cf. plan) : notifie le magasinier des lots dont
la date limite de péremption est atteinte ou approche, pour tous les
tenants. Même structure que ses commandes sœurs (boucle `Tenant.objects.all()` +
`tenant_step`). Planifiée depuis L0-3 : la cadence (quotidienne, 06h) est
déclarée dans `apps.stocks.services.scheduling_registration` et appliquée à
l'ordonnanceur par `manage.py sync_scheduled_commands`.

La déduplication de L0-1 est le préalable de cette planification : sans elle,
le même lot périmant était renotifié à chaque passage.

Nommée `run_expiry_alerts` (pas `expire_...`) pour ne pas être confondue
avec `expire_stock_reservations.py`, déjà existante dans ce même module
pour un concept sans rapport (expiration de réservation de stock, pas
date limite de lot)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step
from apps.stocks.services.expiry_alerts import check_expiring_lots


class Command(BaseCommand):
    help = (
        "FOR-15 : notifie le magasinier des lots dont la date limite de "
        "peremption est atteinte ou approche (stock encore disponible "
        "uniquement), pour tous les tenants."
    )

    def handle(self, *args, **options) -> None:
        total_flagged = 0
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                results = check_expiring_lots(tenant)
            total_flagged += len(results)
            if results:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {len(results)} lot(s) proche(s) de la "
                        "peremption (ou deja perime(s)), notifie(s)."
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Tenant {tenant.code} : aucun lot proche de la peremption detecte."
                    )
                )
        self.stdout.write(self.style.SUCCESS(f"Total : {total_flagged} lot(s) notifie(s)."))
