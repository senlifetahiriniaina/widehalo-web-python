"""Commande ops (§5.5.3, S5, RG-SAL-6) : declenche la generation des
commandes recurrentes arrivees a echeance, pour tous les tenants.

Planifiee depuis L0-3 : la cadence (quotidienne, 05h) est declaree dans
`apps.sales.services.scheduling_registration` et appliquee a l'ordonnanceur
par `manage.py sync_scheduled_commands`.

Utilisateur "commercial" a notifier (RG-SAL-6, "notifie le commercial pour
validation") : `generate_due_order` privilegie toujours le
`salesperson` du gabarit quand il est renseigne. Le parametre `user` de
secours n'est donc utilise ici que pour les gabarits sans commercial
assigne — resolu comme le premier superutilisateur du tenant (systeme
partage entre tenants, cf. `apps.core.models.user.User`, non duplique par
tenant). Un tenant sans aucun superutilisateur est ignore avec un
avertissement plutot que de faire echouer toute la commande."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.scheduled_commands import tenant_step
from apps.sales.services.recurrence import run_due_recurrences


class Command(BaseCommand):
    help = (
        "RG-SAL-6 : genere les commandes recurrentes arrivees a echeance "
        "(brouillon, jamais confirmee) pour tous les tenants."
    )

    def handle(self, *args, **options) -> None:
        total_generated = 0
        for tenant in Tenant.objects.all():
            fallback_user = User.objects.filter(is_superuser=True).order_by("id").first()
            if fallback_user is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"Tenant {tenant.code} : aucun superutilisateur disponible, ignore."
                    )
                )
                continue
            with tenant_step(self, tenant):
                generated = run_due_recurrences(tenant, fallback_user)
            total_generated += len(generated)
            if generated:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {len(generated)} commande(s) generee(s)."
                    )
                )
        self.stdout.write(self.style.SUCCESS(f"Total : {total_generated} commande(s) generee(s)."))
