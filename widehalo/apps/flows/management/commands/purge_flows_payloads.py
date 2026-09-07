"""Commande ops (S6, FLX-5) : purge les charges utiles echues du hub de flux.

Zero logique ici : elle delegue au service et rend son compte. Une commande
qui porterait la regle de retention la rendrait inaccessible aux tests et
aux autres appelants — c'est le patron etabli par
`purge_idempotency_keys` au sprint S4.

Declaree dans `apps.flows.services.scheduling_registration`, appliquee par
`manage.py sync_scheduled_commands`. Sans cette declaration, la commande
existerait sans jamais s'executer : la lecon est ecrite deux fois dans ce
depot, et une troisieme fois serait une negligence.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.flows.services.payload_purge import purge_expired_payloads


class Command(BaseCommand):
    help = (
        "FLX-5 : supprime les charges utiles dont la rétention est échue. "
        "L'échange, son empreinte, son horodatage et son verdict restent intacts."
    )

    def handle(self, *args, **options) -> None:
        count = purge_expired_payloads()
        self.stdout.write(self.style.SUCCESS(f"{count} charge(s) utile(s) purgée(s)."))
