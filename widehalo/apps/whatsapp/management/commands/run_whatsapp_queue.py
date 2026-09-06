"""Commande ops (L10, WA-7) : vide la file d'envoi WhatsApp et relance les
messages en echec, pour tous les tenants.

**C'est le declencheur qui manquait.** `retry_failed_messages` et son
backoff 5 min / 30 min / 2 h existaient depuis le lot WhatsApp initial,
avec exactement deux appelants : un endpoint d'API et un bouton d'ecran.
Autrement dit, « repris automatiquement » reposait entierement sur
quelqu'un qui pense a cliquer. `apps/whatsapp/` n'avait aucun repertoire
`management/`, et le registre d'ordonnancement (`apps.core.services.
scheduled_commands`) comptait dix-neuf commandes, aucune WhatsApp.

La garde `test_scheduled_commands_declared.py` ne pouvait pas le signaler :
elle verifie que toute commande PRESENTE SUR DISQUE est planifiee. Un
module qui n'ecrit aucune commande passe en silence — l'absence ne
declenche rien. C'est le meme angle mort que celui des budgets d'ecrans :
on mesure ce qui existe, jamais ce qui manque.

Meme structure que ses commandes soeurs (boucle `Tenant.objects.all()` +
`tenant_step`, qui isole l'echec d'un tenant pour ne pas priver les
suivants). Cadence declaree dans `apps.whatsapp.services.
scheduling_registration`, appliquee par `manage.py sync_scheduled_commands`.

Idempotente au sens de L0-1 : un passage sans message en file ni en echec
n'ecrit rien et n'envoie rien. Deux passages successifs n'envoient jamais
le meme message deux fois — l'envoi fait passer la ligne hors de
`STATUS_PENDING`, et la reprise hors de `STATUS_FAILED`."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step
from apps.whatsapp.services.messaging import process_outbound_queue


class Command(BaseCommand):
    help = (
        "WA-7 : envoie les messages WhatsApp en file d'attente et relance "
        "ceux en échec, pour tous les tenants."
    )

    def handle(self, *args, **options) -> None:
        total_sent = 0
        total_retried = 0
        for tenant in Tenant.objects.all():
            counts = {"sent": 0, "retried": 0}
            with tenant_step(self, tenant):
                counts = process_outbound_queue(tenant)
            total_sent += counts["sent"]
            total_retried += counts["retried"]
            if counts["sent"] or counts["retried"]:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {counts['sent']} message(s) envoyé(s) "
                        f"depuis la file, {counts['retried']} relancé(s)."
                    )
                )
        self.stdout.write(
            self.style.SUCCESS(
                f"Total : {total_sent} envoyé(s) depuis la file, {total_retried} relancé(s)."
            )
        )
