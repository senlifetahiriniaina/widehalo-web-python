"""Commande ops (§5.8, ST5, RG-STK-8) : expire les reservations de stock
perimees pour tous les tenants. Mirroir exact de
`apps.purchase.management.commands.run_purchase_reordering`/
`apps.sales.management.commands.run_sales_recurrences` : meme structure
(boucle `Tenant.objects.all()` + `activate_tenant`), meme absence
deliberee de cablage automatique dans un `Schedule` de cron — aucun
mecanisme de cron n'est encore cable ailleurs dans le projet pour ce type
de tache, donc aucun n'est invente ici : cette commande est destinee a
etre invoquee par un processus ops/humain (cron systeme ou, plus tard,
une entree de planification Django-Q2), jamais auto-enregistree."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step
from apps.stocks.services.reservations import DEFAULT_MAX_AGE_DAYS, expire_stale_reservations


class Command(BaseCommand):
    help = (
        "RG-STK-8 : libere (etat 'expired') les reservations de stock actives "
        "depassant le delai parametrable (defaut "
        f"{DEFAULT_MAX_AGE_DAYS} jours), pour tous les tenants."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--max-age-days",
            type=int,
            default=DEFAULT_MAX_AGE_DAYS,
            help="Delai (en jours) au-dela duquel une reservation active est expiree.",
        )

    def handle(self, *args, **options) -> None:
        max_age_days = options["max_age_days"]
        total_expired = 0
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                expired = expire_stale_reservations(tenant, max_age_days=max_age_days)
            total_expired += expired
            if expired:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {expired} reservation(s) expiree(s)."
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"Tenant {tenant.code} : aucune reservation perimee a expirer."
                    )
                )
        self.stdout.write(self.style.SUCCESS(f"Total : {total_expired} reservation(s) expiree(s)."))
