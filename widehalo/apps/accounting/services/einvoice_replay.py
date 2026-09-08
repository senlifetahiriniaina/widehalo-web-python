"""T4 (bloc C, EFA-3) — la reprise à l'ouverture du raccordement.

**Le critère** : « L'ouverture d'un raccordement provoque le rejeu de la
file en attente **dans l'ordre chronologique, sans perte, sans doublon**
et sans intervention manuelle autre que la confirmation initiale. »

**Ce que « la file en attente » désigne exactement, et pourquoi ce n'est
pas la file du hub.** Tant qu'aucune liaison n'existe, aucun échange ne
peut exister non plus : `prepare_exchange` part d'une liaison, et en
fabriquer une factice pour avoir une file créerait un enrôlement que
personne n'a demandé. La file d'attente du mode dégradé est donc l'ensemble
des pièces en `A_SOUMETTRE` — produites, signées, archivées, et qui
attendent une destination. C'est cet ensemble que ce module rejoue.

Une fois la liaison ouverte, la file redevient celle du hub, et S3 la
draine déjà dans le bon ordre : `due_exchanges` trie par ancienneté de
CRÉATION, pas par échéance, précisément pour que l'ordre chronologique
soit tenu quel que soit l'état des échanges.

**Sans doublon, et c'est gratuit.** Une pièce déjà soumise n'est plus en
`A_SOUMETTRE` — elle est en `ATTENTE_VERDICT` — donc elle n'entre pas dans
la file. Et si deux rejeux se chevauchaient, la clef d'idempotence du hub,
calculée sur (liaison, pièce, opération), refuserait le second en base.
Deux garde-fous à des étages différents : l'un évite le travail, l'autre
le rend impossible.

**Sans intervention manuelle autre que la confirmation initiale.** C'est
`open_fiscal_link` qui porte cette confirmation : activer la liaison EST
la décision humaine, et le rejeu la suit sans qu'on ait à le demander.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING

from apps.accounting.services.einvoice_submission import (
    CONNECTOR_CODE,
    OUTCOME_QUEUED,
    submit_invoice,
)

if TYPE_CHECKING:
    from apps.accounting.models import AccMove
    from apps.core.models.tenant import Tenant

#: Plafond d'un rejeu, par passe. Une reprise n'est pas une urgence : mille
#: factures d'un coup satureraient la file du tiers le jour même de
#: l'ouverture, et le cahier fait du coût imputé une décision structurante.
#: Le reste part à la passe suivante — la file ne perd rien.
REPLAY_BATCH = 500


@dataclass(frozen=True)
class ReplayReport:
    """Ce qu'une passe de rejeu a fait. Chiffré, pour que l'exploitant
    sache où il en est sans lire un journal."""

    considered: int
    queued: int
    still_pending: int


def pending_submissions(tenant: Tenant, *, limit: int = REPLAY_BATCH) -> list[AccMove]:
    """Les pièces qui attendent une destination, LES PLUS ANCIENNES D'ABORD.

    L'ordre est celui de la DATE DE PIÈCE puis de la création, et non le
    seul `created_at` : deux factures saisies le même jour pour des dates
    différentes doivent partir dans l'ordre où elles ont été émises, pas
    dans celui où quelqu'un les a tapées. C'est ce que « chronologique »
    veut dire pour une administration fiscale."""
    from apps.accounting.models import AccMove

    return list(
        AccMove.objects.filter(tenant=tenant, fiscal_state=AccMove.FISCAL_STATE_TO_SUBMIT).order_by(
            "date", "created_at"
        )[:limit]
    )


def replay_pending_submissions(
    tenant: Tenant, *, now: dt.datetime | None = None, limit: int = REPLAY_BATCH
) -> ReplayReport:
    """Rejoue la file en attente. Idempotent, et sans perte.

    Une pièce qui ne peut toujours pas partir — mention devenue manquante
    parce qu'on a vidé une fiche tiers entre-temps — reste en attente
    plutôt que d'être écartée : « sans perte » vaut aussi pour ce qui
    échoue encore."""
    en_attente = pending_submissions(tenant, limit=limit)
    partis = 0
    for piece in en_attente:
        if submit_invoice(piece, now=now).outcome == OUTCOME_QUEUED:
            partis += 1
    return ReplayReport(
        considered=len(en_attente),
        queued=partis,
        still_pending=len(en_attente) - partis,
    )


def open_fiscal_link(tenant: Tenant, *, now: dt.datetime | None = None) -> ReplayReport:
    """Active la liaison fiscale et rejoue ce qui attendait.

    **La confirmation initiale est l'activation elle-même** — c'est la
    seule intervention manuelle que le critère tolère. Tout ce qui suit
    part sans qu'on le demande.

    Une liaison déjà active est réactivée sans effet : rejouer la file d'un
    raccordement déjà ouvert est exactement ce qu'on veut pouvoir faire
    après un incident, et refuser au motif que « c'est déjà ouvert »
    obligerait à suspendre puis rouvrir pour rattraper un retard."""
    from apps.flows.services.public import activate_link

    activate_link(tenant, connector_code=CONNECTOR_CODE)
    return replay_pending_submissions(tenant, now=now)


__all__ = [
    "REPLAY_BATCH",
    "ReplayReport",
    "open_fiscal_link",
    "pending_submissions",
    "replay_pending_submissions",
]
