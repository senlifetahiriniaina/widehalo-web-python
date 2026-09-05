"""Commande ops (Bloc D, D3, QUA-9) : declenche la verification de
controle du/en retard pour tous les tenants. Mirroir exact de
`apps.purchase.management.commands.run_price_watch_checks` : meme
structure (boucle `Tenant.objects.all()` + `activate_tenant`), meme
absence deliberee de cablage automatique dans un `Schedule`/cron — aucun
mecanisme de cron n'est cable ailleurs dans le projet pour ce type de
tache, donc aucun n'est invente ici : cette commande est destinee a etre
invoquee par un processus ops/humain (cron systeme, ou plus tard une
entree de planification Django-Q2), jamais auto-enregistree."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step
from apps.quality.services.public import check_overdue_controls


class Command(BaseCommand):
    help = (
        "QUA-9 : notifie les rôles qualité des lots dont le contrôle "
        "est dû ou en retard, pour tous les tenants."
    )

    def handle(self, *args, **options) -> None:
        total_overdue = 0
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                results = check_overdue_controls(tenant=tenant)
            total_overdue += len(results)
            if results:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {len(results)} lot(s) en retard de "
                        "contrôle, notifié(s)."
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f"Tenant {tenant.code} : aucun contrôle en retard détecté.")
                )
        self.stdout.write(
            self.style.SUCCESS(f"Total : {total_overdue} lot(s) en retard notifié(s).")
        )
