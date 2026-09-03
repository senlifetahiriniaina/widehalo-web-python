from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core.models.tenant import Tenant
from apps.core.services.regulatory_governance import unvalidated_active_parameters


class Command(BaseCommand):
    help = (
        "Verrou de mise en production (cahier des charges WideHalo v3, Phase 1, "
        "§13.3, ACC-9) : sort en erreur (code 1) si un RegulatoryParameter "
        "actuellement effectif, pour un code utilise par un calcul actif "
        "(apps.core.services.regulatory_governance.ACTIVE_CALCULATION_PARAMETER_CODES), "
        "porte encore le statut NON_VALIDE. A executer avant toute mise en "
        "production (cf. docs/DEPLOYMENT_HETZNER.md) — jamais contourne au motif "
        "que le deploiement doit avancer."
    )

    def handle(self, *args: object, **options: object) -> None:
        tenants = list(Tenant.objects.all())
        blocking = unvalidated_active_parameters(tenants=tenants)

        if not blocking:
            self.stdout.write(
                self.style.SUCCESS(
                    "Aucun paramètre réglementaire actif non validé — déploiement autorisé."
                )
            )
            return

        lines = [
            f"  - {row.code} (tenant={row.tenant_id or 'global'}, version={row.version}, "
            f"effectif depuis {row.valid_from})"
            for row in blocking
        ]
        raise CommandError(
            "Déploiement bloqué : "
            f"{len(blocking)} paramètre(s) réglementaire(s) actif(s) non validé(s) "
            "par un expert-comptable OECFM :\n" + "\n".join(lines)
        )
