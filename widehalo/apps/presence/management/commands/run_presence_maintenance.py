"""Commande ops (PR6) : regroupe 3 taches de maintenance `presence`,
destinee a etre invoquee periodiquement par une tache externe (cron
systeme) — meme discipline que `apps.sales.management.commands.
run_sales_recurrences`/`apps.purchase.management.commands.
run_purchase_reordering` : aucun cron n'est auto-enregistre par ce lot,
seule cette commande appelable existe.

1. RG-PRS-2 : purge la geolocalisation precise des pointages de plus de
   30 jours (`purge_expired_geolocation`), tous tenants confondus (pas de
   notion de tenant sur cette fonction, deja globale).
2. RG-PRS-6 : bascule en "injustifie" les absences sans justificatif
   toujours en attente au-dela du delai parametre.
3. PRS-DOC1 : notifie le role `rh` des documents employe arrivant a
   echeance (meme patron que `apps.logistics.services.vehicles.
   upcoming_document_alerts`/`notify_document_alert`, RG-LOG-1)."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tenant_context import activate_tenant
from apps.presence.models import PrsAbsenceType
from apps.presence.services.absences import (
    mark_unjustified_if_overdue,
    pending_unjustified_candidates,
)
from apps.presence.services.documents_tracking import (
    notify_document_alert,
    upcoming_document_alerts,
)
from apps.presence.services.retention import purge_expired_geolocation


class Command(BaseCommand):
    help = (
        "Maintenance presence : purge geolocalisation 30j, bascule injustifie, alertes documents."
    )

    def handle(self, *args, **options) -> None:
        purged = purge_expired_geolocation()
        self.stdout.write(self.style.SUCCESS(f"{purged} geolocalisation(s) purgee(s)."))

        total_unjustified = 0
        total_alerts = 0
        for tenant in Tenant.objects.all():
            with activate_tenant(tenant.id):
                unjustified_type = PrsAbsenceType.objects.filter(
                    tenant=tenant, category=PrsAbsenceType.CATEGORY_UNJUSTIFIED
                ).first()
                if unjustified_type is not None:
                    for absence in pending_unjustified_candidates(tenant):
                        if mark_unjustified_if_overdue(absence, unjustified_type=unjustified_type):
                            total_unjustified += 1

                recipient = User.objects.filter(
                    groups__name="rh", tenant_memberships__tenant_id=tenant.id
                ).first()
                if recipient is not None:
                    for document in upcoming_document_alerts(tenant):
                        notify_document_alert(document, recipient=recipient)
                        total_alerts += 1

        self.stdout.write(
            self.style.SUCCESS(f"{total_unjustified} absence(s) basculee(s) injustifie.")
        )
        self.stdout.write(self.style.SUCCESS(f"{total_alerts} alerte(s) document envoyee(s)."))
