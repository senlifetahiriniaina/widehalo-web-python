"""T3 (OP8) — fait vérifier les identifiants fiscaux auprès du référentiel,
et relit les verdicts arrivés.

**Pourquoi une commande périodique et non un appel à la saisie.** Le cahier
décrit OP8 comme « synchrone », mais deux règles déjà tenues l'interdisent
telle quelle : aucun module métier n'émet d'appel réseau (règle de couplage
n°1, garde CI depuis S6), et l'échec d'un tiers ne bloque jamais une
transition métier (FLX-2). Vérifier à la saisie ferait dépendre la création
d'un tiers de la latence d'un référentiel — exactement ce que le hub existe
pour éviter.

La demande part donc en file, et cette commande fait les deux moitiés du
travail : elle **demande** pour les tiers dont la vérification manque ou a
expiré, et elle **relit** les verdicts arrivés depuis la passe précédente.
C'est ce qui donne un appelant de production à
`partners_needing_verification` et à `refresh_verification` — sans elle,
les deux seraient du code juste que rien n'invoque, le motif que ce dépôt
corrige à chaque lot.

**Sans référentiel branché, elle ne fait rien et le dit.** La majorité des
installations n'auront jamais de liaison vers un référentiel fiscal :
c'est un état normal, pas une panne.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.core.models.tenant import Tenant
from apps.core.tenant_context import activate_tenant
from apps.partners.services.fiscal_verification import (
    partners_needing_verification,
    refresh_verification,
    request_verification,
)


class Command(BaseCommand):
    help = "Demande la vérification des identifiants fiscaux et relit les verdicts arrivés."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--tenant-code", default="", help="Limite à une société.")
        parser.add_argument(
            "--max-requests",
            type=int,
            default=200,
            help=(
                "Plafond de demandes par passe et par société. Un référentiel "
                "n'est pas une ressource illimitée, et une base de dix mille "
                "tiers ne doit pas partir d'un coup."
            ),
        )

    def handle(self, *args: object, **options: object) -> None:
        code = str(options.get("tenant_code") or "")
        plafond = int(str(options.get("max_requests") or 200))
        tenants = Tenant.objects.filter(code=code) if code else Tenant.objects.all()

        for tenant in tenants.order_by("code"):
            with activate_tenant(tenant.id):
                relus = self._refresh_pending(tenant)
                demandes = self._request_missing(tenant, plafond)
            self.stdout.write(
                f"{tenant.code} — {relus} verdict(s) relu(s), {demandes} demande(s) émise(s)."
            )

    def _refresh_pending(self, tenant: Tenant) -> int:
        """Relit les verdicts des tiers dont la réponse manque ou a expiré.

        On ne relit pas toute la base à chaque nuit — ce serait une lecture
        d'échanges par tiers pour ne rien apprendre. Mais la file à relire
        n'est pas seulement celle des « pas encore répondu » : une
        CONFIRMATION PÉRIMÉE en fait partie aussi. L'omettre laissait un
        trou dont la conséquence est silencieuse — la fiche restait
        « confirmée » à sa vieille date, `_request_missing` la voyait donc
        encore périmée, et en redemandait la vérification chaque nuit sans
        que le verdict revenu ne soit jamais lu.

        C'est exactement la même file que `partners_needing_verification`,
        et c'est voulu : demander et relire portent sur le même ensemble,
        décalés d'une passe."""
        relus = 0
        for partenaire in partners_needing_verification(tenant):
            avant = (partenaire.fiscal_verification_state, partenaire.fiscal_verified_at)
            apres = refresh_verification(partenaire)
            if (apres.fiscal_verification_state, apres.fiscal_verified_at) != avant:
                relus += 1
        return relus

    def _request_missing(self, tenant: Tenant, plafond: int) -> int:
        demandes = 0
        for partenaire in partners_needing_verification(tenant)[:plafond]:
            if request_verification(partenaire) is not None:
                demandes += 1
        return demandes
