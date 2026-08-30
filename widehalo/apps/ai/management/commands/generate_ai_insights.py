"""Commande ops (AI5) : declenche `generate` pour tous les tenants. Meme
discipline exacte que `apps.ai.management.commands.run_ai_anomaly_checks`
(AI3) : AUCUN mecanisme de cron n'est cable ici ni ailleurs pour cette
commande — seule cette commande appelable existe, un ops humain ou un
cron externe la declenche."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.ai.services.automated_insights import generate
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant


class Command(BaseCommand):
    help = (
        "AI5 : execute toutes les sources d'insights proactifs enregistrees, pour tous les tenants."
    )

    def handle(self, *args, **options) -> None:
        total_created = 0
        for tenant in Tenant.objects.all():
            with activate_tenant(tenant.id):
                created = generate(tenant)
            total_created += len(created)
            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {len(created)} insight(s) genere(s)."
                    )
                )
        self.stdout.write(self.style.SUCCESS(f"Total : {total_created} insight(s) genere(s)."))
