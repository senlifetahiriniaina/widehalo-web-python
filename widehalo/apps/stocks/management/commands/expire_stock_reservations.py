"""Commande ops (§5.8, ST5, RG-STK-8) : expire les reservations de stock
perimees pour tous les tenants.

Meme structure que ses commandes soeurs (boucle `Tenant.objects.all()` +
`tenant_step`). Planifiee depuis L0-3 : la cadence (quotidienne, 02h) est
declaree dans `apps.stocks.services.scheduling_registration` et appliquee a
l'ordonnanceur par `manage.py sync_scheduled_commands`."""

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
