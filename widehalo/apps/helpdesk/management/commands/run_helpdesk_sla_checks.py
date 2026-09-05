"""Commande ops (HD2, cf. plan section « SLA et escalade ») : declenche
`sla.check_breaches`/`escalation.run_escalation_checks` pour tous les
tenants. Mirroir exact de `apps.purchase.management.commands.
run_purchase_reordering`/`apps.presence.management.commands.
run_presence_maintenance` : meme structure (boucle `Tenant.objects.all()`
+ `activate_tenant`), meme absence deliberee de cablage automatique dans
un `Schedule`/cron — aucun mecanisme de cron n'est cable ailleurs dans le
projet pour ce type de tache, donc aucun n'est invente ici : cette
commande est destinee a etre invoquee par un processus ops/humain (cron
systeme, ou plus tard une entree de planification Django-Q2), jamais
auto-enregistree.

**Pas de "fallback superuser" necessaire ici** (contrairement a `apps.
sales.management.commands.run_sales_recurrences`) : ni `check_breaches`
ni `run_escalation_checks` n'exigent d'utilisateur reel — la transition
FSM `escalate` de `HlpTicket` ne declare aucun `permission=` (cf.
`apps.helpdesk.services.escalation.run_escalation_checks`, docstring),
et les notifications (`notify_role`/`dispatch_notification`) sont
adressees a des roles/equipes, jamais a un "acteur" de la commande. Un
tenant sans aucune regle/politique active est simplement ignore (listes
vides retournees), jamais une erreur."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step
from apps.helpdesk.services import escalation, sla


class Command(BaseCommand):
    help = (
        "HD2 : verifie les breches de SLA et les regles d'escalade helpdesk "
        "pour tous les tenants, recalcule le score de risque des tickets actifs."
    )

    def handle(self, *args, **options) -> None:
        total_breaches = 0
        total_escalations = 0
        for tenant in Tenant.objects.all():
            with tenant_step(self, tenant):
                breaches = sla.check_breaches(tenant)
                events = escalation.run_escalation_checks(tenant)
            total_breaches += len(breaches)
            total_escalations += len(events)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Tenant {tenant.code} : {len(breaches)} breche(s) SLA, "
                    f"{len(events)} escalade(s) automatique(s)."
                )
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Total : {total_breaches} breche(s) SLA, {total_escalations} escalade(s)."
            )
        )
