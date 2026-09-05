"""Commande ops (AI5) : declenche `generate` pour tous les tenants.

Planifiee depuis L0-3 : la cadence (hebdomadaire, 04h) est declaree dans
`apps.ai.services.scheduling_registration` et appliquee a l'ordonnanceur par
`manage.py sync_scheduled_commands`. Reste appelable a la main."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.ai.services.automated_insights import generate
from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step


class Command(BaseCommand):
    help = (
        "AI5 : execute toutes les sources d'insights proactifs enregistrees, pour tous les tenants."
    )

    def handle(self, *args, **options) -> None:
        total_created = 0
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                created = generate(tenant)
            total_created += len(created)
            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {len(created)} insight(s) genere(s)."
                    )
                )
        self.stdout.write(self.style.SUCCESS(f"Total : {total_created} insight(s) genere(s)."))
