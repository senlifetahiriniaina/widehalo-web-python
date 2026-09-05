"""L0-3 — commande de deploiement qui aligne l'ordonnanceur sur le registre.

Volontairement une commande et non un appel depuis `AppConfig.ready()` :
ecrire des planifications au chargement des applications ferait dependre le
demarrage du serveur de l'etat de la base et casserait `migrate` sur une base
neuve. Les `ready()` des apps DECLARENT, ce deploiement SYNCHRONISE.

A lancer apres chaque deploiement, au meme titre que `migrate` et
`load_roles` (cf. `docs/DEPLOYMENT_HETZNER.md`). Idempotente : deux
executions consecutives laissent la meme planification.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.core.services.scheduled_commands import list_scheduled_commands
from apps.core.tasks import sync_schedules


class Command(BaseCommand):
    help = (
        "Synchronise les planifications de l'ordonnanceur sur le registre des "
        "commandes periodiques (apps.core.services.scheduled_commands). "
        "Idempotente ; supprime les planifications devenues orphelines."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--list",
            action="store_true",
            dest="list_only",
            help="Affiche le registre sans rien ecrire (controle avant deploiement).",
        )

    def handle(self, *args, **options) -> None:
        entries = list_scheduled_commands()

        if options["list_only"]:
            for entry in entries:
                self.stdout.write(
                    f"{entry.code} — {entry.command} ({entry.frequency}, {entry.hour:02d}h) "
                    f"[{entry.module}] {entry.label}"
                )
            self.stdout.write(
                self.style.SUCCESS(f"{len(entries)} commande(s) périodique(s) déclarée(s).")
            )
            return

        if not entries:
            # Le registre est peuple par les `ready()` des apps : un registre
            # vide signale une application non chargee, pas un depot sans
            # traitement periodique. Effacer les planifications sur cette base
            # desarmerait l'ordonnanceur en silence.
            self.stdout.write(
                self.style.ERROR(
                    "Registre vide : aucune commande périodique déclarée. "
                    "Synchronisation abandonnée pour ne pas désarmer l'ordonnanceur."
                )
            )
            return

        result = sync_schedules()
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(entries)} commande(s) périodique(s) déclarée(s) : "
                f"{result['created']} planification(s) créée(s), "
                f"{result['updated']} mise(s) à jour, "
                f"{result['deleted']} supprimée(s)."
            )
        )
