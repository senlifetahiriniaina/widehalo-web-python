"""Commande ops (S3, FLX-3) : vide la file de sortie du hub de flux.

**Livree AVEC la file, et pas au sprint qui livrera le premier
adaptateur.** La lecon est ecrite six sprints plus tot dans ce meme depot :
la reprise WhatsApp et son backoff existaient depuis le lot initial, avec
pour seuls declencheurs un endpoint et un bouton — autrement dit
« repris automatiquement » reposait sur quelqu'un qui pense a cliquer.
Livrer une file de sortie sans son declencheur reproduirait exactement ce
defaut, et personne ne s'en apercevrait avant le premier connecteur reel.

**Ce que cette commande fait aujourd'hui, sans embellir : rien**, parce que
le registre d'adaptateurs est vide jusqu'au sprint S6. Elle parcourt la
file, ne trouve aucun connecteur adressable, et laisse tout en place. Un
zero qui ne prouve rien serait du theatre : c'est pourquoi
`test_s3_queue_command.py` enregistre un adaptateur factice et verifie que
la commande envoie REELLEMENT — le compteur sait compter, ce sont les
adaptateurs qui manquent.

Cadence HORAIRE, meme motif que la file WhatsApp : l'espacement de reessai
par defaut demarre a cinq minutes, et un declencheur quotidien rendrait le
premier delai utile de vingt-quatre heures. Declaree dans
`apps.flows.services.scheduling_registration`, appliquee par
`manage.py sync_scheduled_commands`.

Idempotente : une passe sans echange du ni adaptateur n'ecrit rien. Deux
passes successives n'envoient pas deux fois le meme echange — l'envoi le
sort de `en_file`, et l'echec lui pose une echeance que la passe suivante
respecte.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.services.scheduled_commands import tenant_step
from apps.flows.services.adapter_registry import list_adapters
from apps.flows.services.queue import process_outbound_queue


class Command(BaseCommand):
    help = (
        "FLX-3 : vide la file de sortie du hub de flux — envoie les échanges en "
        "attente, respecte le réessai espacé et le disjoncteur de chaque liaison."
    )

    def handle(self, *args, **options) -> None:
        adapters = list_adapters()
        if not adapters:
            # Dit plutot que tu : une passe silencieuse qui ne fait rien est
            # indiscernable d'une passe qui echoue.
            self.stdout.write(
                self.style.WARNING(
                    "Aucun adaptateur enregistré : les échanges restent en file, sans "
                    "appel ni échec. C'est l'état attendu tant que le bloc A n'a pas "
                    "livré son adaptateur (sprint S6)."
                )
            )

        totals = {"sent": 0, "failed": 0, "skipped_breaker": 0, "skipped_no_adapter": 0}
        for tenant in Tenant.objects.all():
            counts: dict[str, int] = {}
            with tenant_step(self, tenant):
                counts = process_outbound_queue(tenant)
            for key in totals:
                totals[key] += counts.get(key, 0)
            if counts.get("sent") or counts.get("failed"):
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Tenant {tenant.code} : {counts['sent']} échange(s) parti(s), "
                        f"{counts['failed']} en échec, "
                        f"{counts['skipped_breaker']} retenu(s) par un disjoncteur."
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Total : {totals['sent']} parti(s), {totals['failed']} en échec, "
                f"{totals['skipped_breaker']} retenu(s) par un disjoncteur, "
                f"{totals['skipped_no_adapter']} sans adaptateur."
            )
        )
