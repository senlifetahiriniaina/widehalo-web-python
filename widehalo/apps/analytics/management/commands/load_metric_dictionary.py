from __future__ import annotations

from django.core.management.base import BaseCommand, CommandParser

from apps.analytics.services.starting_metrics import load_metric_dictionary
from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant


class Command(BaseCommand):
    """L8 — charge le jeu d'indicateurs de depart du dictionnaire gouverne.

    Meme famille que `load_chart_of_accounts`/`load_default_journals` : un
    chargement de referentiel, idempotent, appele aux quatre points de
    creation/reinitialisation de tenant.

    Il comble un vide, pas une commodite : `AnMetricDefinition` etait
    presente comme « la SEULE voie declaree d'acces aux donnees
    decisionnelles » et rien ne la peuplait. Sur une instance neuve l'ecran
    du dictionnaire etait vide, aucun rapport BI ne pouvait nommer un
    indicateur, et `strategy` refusait tout resultat cle adosse a un code
    (STR-1) puisque aucun code n'existait.
    """

    help = (
        "Charge le jeu d'indicateurs de depart du dictionnaire gouverne "
        "(idempotent). Sans lui, le dictionnaire d'un tenant neuf reste vide."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--tenant", required=True, help="Code du tenant")

    def handle(self, *args, **options) -> None:
        tenant = Tenant.objects.get(code=options["tenant"])
        with activate_tenant(tenant.id):
            total = load_metric_dictionary(tenant)
        self.stdout.write(
            self.style.SUCCESS(
                f"{total} indicateur(s) au dictionnaire de {tenant.code} apres chargement."
            )
        )
