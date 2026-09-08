"""T4 (bloc C, EFA-4, EFA-5, EFA-3) — recevoir un verdict, et ce qu'on en fait.

**EFA-4** : « Le verdict reçu est conservé **dans sa forme d'origine, en
plus de son interprétation** ; l'identifiant attribué et le marquage
vérifiable sont reportés sur la représentation lisible du document. »

Les deux moitiés sont deux champs distincts, et les séparer n'est pas de
la redondance. `AccMove.fiscal_state` est l'INTERPRÉTATION — cinq valeurs
qu'un écran sait afficher et qu'un total sait compter.
`fiscal_verdict_raw` est ce que l'administration a réellement répondu, tel
quel. Une interprétation est révisable : le jour où l'on découvre qu'un
code de rejet signifiait autre chose, on relit les verdicts bruts et on
corrige la lecture. Si l'on n'avait gardé que l'interprétation, il n'y
aurait rien à relire.

**EFA-5** : « Un rejet affiche un motif actionnable par un comptable et
propose une reprise ; la correction produit un **nouvel échange**, jamais
une modification de l'échange rejeté. »

Ce module ne rouvre donc jamais un échange. Le hub l'interdit déjà en
base — `FlwExchange.STATE_REJECTED` est terminal, sans transition
sortante — et la reprise passe par `submit_invoice`, qui en crée un neuf.
La garde est double parce que les deux disent des choses différentes : la
machine à états empêche l'écriture, ce module empêche même l'intention.

**Le marquage sur la représentation lisible.** Deux documents, jamais un
seul : RPT-9 impose qu'un PDF de facture ne soit produit qu'une fois et
resservi octet-pour-octet, quand EFA-4 exige que le marquage soit reporté
sur la représentation lisible. Ce qui est archivé à la soumission est ce
qui PART, figé ; la représentation marquée est produite ici, quand le
verdict arrive, et elle est un second document. C'est aussi ce que fait un
vrai dispositif : la facture qu'on soumet et celle qu'on remet au client
ne sont pas le même papier.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.utils import timezone

if TYPE_CHECKING:
    from apps.accounting.models import AccMove

#: Ce que chaque état d'échange dit du sort fiscal de la pièce. Table
#: EXPLICITE plutôt qu'une suite de `if` : un état d'échange neuf doit
#: obliger quelqu'un à décider ce qu'il signifie ici, pas glisser dans un
#: `else` qui le traiterait comme une acceptation. Même discipline que
#: `partners.services.fiscal_verification.VERDICT_PAR_ETAT` (T3).
FISCAL_STATE_BY_EXCHANGE_STATE: dict[str, str] = {
    "accepte": "accepte",
    "rejete": "rejete",
}


@dataclass(frozen=True)
class VerdictSummary:
    """Ce qu'un écran doit pouvoir dire du sort fiscal d'une pièce."""

    fiscal_state: str
    fiscal_reference: str
    settled_at: dt.datetime | None
    raw: str
    #: Le motif, quand il y en a un — EFA-5 exige qu'il soit « actionnable
    #: par un comptable », donc lisible et non un code.
    reason: str = ""

    @property
    def is_rejected(self) -> bool:
        return self.fiscal_state == "rejete"


def record_verdict(
    move: AccMove,
    *,
    exchange_state: str,
    raw: str,
    fiscal_reference: str = "",
    marking: str = "",
    reason: str = "",
    now: dt.datetime | None = None,
) -> AccMove:
    """Inscrit un verdict sur la pièce — la forme d'origine ET sa lecture.

    Ne touche NI `state` NI `invoice_state` : c'est tout l'objet d'EFA-6.
    Une facture déjà encaissée reçoit son verdict sans que son règlement
    ne bouge, et une facture acceptée par l'administration reste due tant
    qu'elle n'est pas payée."""
    from apps.accounting.models import AccMove as Move

    interpretation = FISCAL_STATE_BY_EXCHANGE_STATE.get(exchange_state)
    if interpretation is None:
        # Un échange qui n'a pas tranché ne dit rien du sort fiscal. Ne
        # rien écrire est la bonne réponse : inscrire « en attente » ici
        # écraserait un verdict déjà reçu si deux messages arrivaient dans
        # le désordre, ce qui est le cas normal d'un canal asynchrone.
        return move

    maintenant = now or timezone.now()
    move.fiscal_state = (
        Move.FISCAL_STATE_ACCEPTED if interpretation == "accepte" else Move.FISCAL_STATE_REJECTED
    )
    # La forme d'origine est écrite TELLE QUELLE, sans reformatage ni
    # troncature : c'est elle qui fera foi le jour d'un désaccord.
    move.fiscal_verdict_raw = raw
    move.fiscal_reference = fiscal_reference
    move.fiscal_marking = marking
    move.fiscal_settled_at = maintenant
    move.save(
        update_fields=[
            "fiscal_state",
            "fiscal_verdict_raw",
            "fiscal_reference",
            "fiscal_marking",
            "fiscal_settled_at",
        ]
    )
    return move


def verdict_summary(move: AccMove) -> VerdictSummary:
    """Le sort fiscal de la pièce, pour un écran."""
    return VerdictSummary(
        fiscal_state=move.fiscal_state,
        fiscal_reference=move.fiscal_reference,
        settled_at=move.fiscal_settled_at,
        raw=move.fiscal_verdict_raw,
    )


def refresh_from_exchanges(move: AccMove, *, now: dt.datetime | None = None) -> AccMove:
    """Relit le dernier échange tranché et en inscrit le verdict.

    **La leçon de T3 est appliquée ici avant d'avoir été payée une seconde
    fois** : un verdict RECONDUIT re-date la pièce. Comparer le seul état
    laisserait une acceptation ancienne masquer une soumission plus
    récente, et rien ne le dirait."""
    from apps.accounting.services.einvoice_submission import DOCUMENT_TYPE
    from apps.flows.services.public import list_exchanges_for_document

    for echange in list_exchanges_for_document(
        move.tenant, document_type=DOCUMENT_TYPE, document_id=move.id, limit=5
    ):
        etat = str(echange.get("state", ""))
        if etat not in FISCAL_STATE_BY_EXCHANGE_STATE:
            continue
        tranche_le = echange.get("settled_at")
        if _already_recorded(move, etat, tranche_le):
            return move
        return record_verdict(
            move,
            exchange_state=etat,
            raw=str(echange.get("result_message", "") or ""),
            fiscal_reference=str(echange.get("result_code", "") or ""),
            now=now,
        )
    return move


def _already_recorded(move: AccMove, exchange_state: str, settled_at: Any) -> bool:
    """Ce verdict est-il déjà celui qui est inscrit, et pas plus ancien ?

    Trois conditions, pas une : le même état, une date déjà posée, et une
    date au moins aussi récente que celle de l'échange. Ne comparer que
    l'état ferait manquer une resoumission acceptée après un premier
    refus — exactement le défaut trouvé en T3 sur la re-vérification d'un
    identifiant, où une confirmation reconduite ne re-datait rien."""
    from apps.accounting.models import AccMove as Move

    attendu = (
        Move.FISCAL_STATE_ACCEPTED
        if FISCAL_STATE_BY_EXCHANGE_STATE[exchange_state] == "accepte"
        else Move.FISCAL_STATE_REJECTED
    )
    if move.fiscal_state != attendu or move.fiscal_settled_at is None:
        return False
    if settled_at is None:
        return True
    return bool(move.fiscal_settled_at >= settled_at)


__all__ = [
    "FISCAL_STATE_BY_EXCHANGE_STATE",
    "VerdictSummary",
    "record_verdict",
    "refresh_from_exchanges",
    "verdict_summary",
]
