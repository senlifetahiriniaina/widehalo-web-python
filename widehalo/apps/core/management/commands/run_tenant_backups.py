"""Commande ops (chantier sauvegarde/restauration/reinitialisation) :
declenche `apps.core.services.tenant_backup.run_due_tenant_backups` pour
toutes les planifications actives echues, tous tenants confondus.

**Sans cron auto-enregistre** (decision actee avec l'utilisateur) — meme
convention exacte que tous les jobs planifies deja existants de ce depot
(`run_sales_recurrences`, `run_purchase_reordering`,
`run_presence_maintenance`, `run_helpdesk_sla_checks`,
`run_report_schedules`...) : aucun mecanisme de cron n'est cable ailleurs
dans le projet, donc aucun n'est invente ici — c'est a l'operateur
(cron systeme/Docker) d'invoquer cette commande periodiquement.

**Pas de boucle `Tenant.objects.all()` explicite ici** (contrairement aux
commandes soeurs citees ci-dessus) : `run_due_tenant_backups()` itere deja
lui-meme les `TenantBackupSchedule` echues (tous tenants confondus, chacune
portant son propre `tenant`) et active le contexte tenant correspondant en
interne — dupliquer une boucle par-tenant ici n'ajouterait rien, la
requete `next_run_at__lte=now()` filtre deja precisement le travail a
faire."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.services.tenant_backup import run_due_tenant_backups


class Command(BaseCommand):
    help = (
        "Declenche les sauvegardes de tenant planifiees et echues "
        "(TenantBackupSchedule.next_run_at <= maintenant)."
    )

    def handle(self, *args, **options) -> None:
        operations = run_due_tenant_backups()
        if not operations:
            self.stdout.write(self.style.SUCCESS("Aucune sauvegarde planifiee echue."))
            return
        for operation in operations:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Tenant {operation.tenant.code} : sauvegarde {operation.status} "
                    f"({operation.id})."
                )
            )
        self.stdout.write(
            self.style.SUCCESS(f"Total : {len(operations)} sauvegarde(s) declenchee(s).")
        )
