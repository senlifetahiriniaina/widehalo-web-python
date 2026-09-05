"""Commande ops (BI-7) : diffuse les rapports BI planifiés arrivés à
échéance, pour tous les tenants.

Planifiée depuis L0-3 : la cadence (quotidienne, 06h) est déclarée dans
`apps.bi.services.scheduling_registration` et appliquée à l'ordonnanceur par
`manage.py sync_scheduled_commands`. Reste appelable à la main."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.bi.services.diffusion import run_due_diffusions
from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step


class Command(BaseCommand):
    help = "Diffuse les rapports BI planifiés arrivés à échéance (BI-7), pour tous les tenants."

    def handle(self, *args, **options) -> None:
        total = 0
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                sent = run_due_diffusions(tenant)
            total += sent
            if sent:
                self.stdout.write(self.style.SUCCESS(f"Tenant {tenant.code} : {sent} envoi(s)."))
        self.stdout.write(self.style.SUCCESS(f"Total : {total} envoi(s)."))
