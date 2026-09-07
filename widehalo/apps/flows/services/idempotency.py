"""S4 — la clef d'idempotence SORTANTE et la clef de correlation.

Le cahier (§13.4) demande trois choses distinctes que le mot « rejeu »
confond en francais courant, et les confondre rend FLX-4 inapplicable.

**L'IDEMPOTENCE** protege le TIERS d'un doublon. « Chaque echange sortant
porte une cle calculee sur la piece, la liaison et le rang de tentative,
transmise au tiers lorsqu'il l'admet. Un rejeu produit la meme cle et ne
cree donc pas de doublon chez le tiers. »

Il y a la une contradiction interne qu'il faut trancher, et le critere
tranche : si la clef incluait le rang de tentative, elle CHANGERAIT a
chaque tentative — ce qui annule exactement ce que la phrase suivante
promet, et ce que FLX-4 exige (« un rejeu d'un echange sortant transmet la
MEME cle d'idempotence »). « Rang de tentative » ne peut donc designer que
le rang du REJEU SUPERVISE — c'est-a-dire le rang du successeur — et non
le compteur `attempt` du reessai technique. C'est l'arbitrage deja ecrit
sur `FlwExchange.idempotency_key`, applique ici.

**LA CORRELATION** relie les trois choses qu'un rapprochement doit joindre :
« l'echange sortant, la notification entrante qui lui repond et la piece
metier concernee. Sans elle, un paiement notifie trois jours plus tard
n'est plus rattachable a ce qui l'a declenche. » Elle ne protege rien —
elle RETROUVE.

**Pourquoi les deux clefs ne peuvent pas etre la meme.** L'idempotence doit
etre UNIQUE par echange (sans quoi le tiers ignorerait une resoumission
legitime) ; la correlation doit etre PARTAGEE par toute une lignee (sans
quoi elle ne relierait rien). Une seule clef ne peut pas etre a la fois
unique et partagee. C'est pourquoi le modele en porte deux, et c'est la
seule raison.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from apps.flows.models import FlwExchange

if TYPE_CHECKING:
    from uuid import UUID

#: Longueur de la clef produite. Les 32 premiers caracteres d'un SHA-256
#: (128 bits) : assez pour qu'une collision soit hors de portee, assez
#: court pour tenir dans l'en-tete d'un tiers qui plafonne souvent a 64
#: caracteres. Le champ en accepte 128, la marge est deliberée.
KEY_LENGTH = 32


def compute_idempotency_key(
    *,
    link_id: UUID,
    document_type: str,
    document_id: UUID | None,
    operation: str,
    replay_rank: int = 0,
) -> str:
    """La clef transmise au tiers.

    Calculee sur (liaison, piece, operation, rang de REJEU) — jamais sur le
    compteur de tentatives techniques. Deux tentatives du meme envoi
    produisent donc la meme clef, ce qui est exactement ce que FLX-4
    demande ; deux rejeux supervises successifs en produisent deux
    differentes, ce que la contrainte d'unicite en base impose de toute
    facon.

    **L'operation entre dans la clef**, et ce n'est pas evident : une meme
    piece peut partir deux fois vers la meme liaison pour deux operations
    differentes — soumettre une facture, puis en demander le statut. Sans
    l'operation, la seconde porterait la clef de la premiere et le tiers
    l'ignorerait comme un doublon.

    **Une piece nulle est admise** : certaines operations n'en ont pas
    (relever un statut global, recuperer un jeton). La clef reste alors
    stable pour le couple (liaison, operation), ce qui est le comportement
    voulu — deux relevés simultanes ne doivent pas compter double."""
    graine = "|".join(
        [
            str(link_id),
            document_type,
            str(document_id) if document_id else "",
            operation,
            str(replay_rank),
        ]
    )
    return hashlib.sha256(graine.encode("utf-8")).hexdigest()[:KEY_LENGTH]


def compute_correlation_key(*, document_type: str, document_id: UUID | None) -> str:
    """La clef qui relie une lignee a sa piece metier.

    Calculee sur la seule PIECE, volontairement : c'est ce qui permet a une
    notification entrante — qui ne connait ni la liaison ni l'operation, et
    arrive parfois trois jours plus tard — de retrouver l'echange qui l'a
    declenchee. Y inclure la liaison rendrait la clef incalculable depuis
    le cote entrant, et la correlation ne relierait plus rien.

    Chaine vide pour une operation sans piece : correler ce qui ne se
    rattache a rien produirait des grappes d'echanges sans lien entre eux,
    et le journal deviendrait illisible la ou il doit etre le plus clair."""
    if not document_id:
        return ""
    return f"{document_type}:{document_id}"


def assign_keys(exchange: FlwExchange, *, replay_rank: int = 0) -> FlwExchange:
    """Pose les deux clefs sur un echange qui n'en a pas encore.

    **Au moment de la MISE EN FILE, pas de la preparation.** Un echange
    prepare puis abandonne sans jamais partir ne doit pas consommer une
    clef : la contrainte d'unicite la retiendrait pour toujours, et une
    seconde tentative sur la meme piece serait refusee par la base pour un
    envoi qui n'a jamais eu lieu.

    Idempotente elle-meme : rappelee sur un echange deja clave, elle ne
    recalcule rien. Recalculer changerait la clef transmise au tiers entre
    deux tentatives du meme envoi — soit precisement le defaut que FLX-4
    interdit."""
    if exchange.idempotency_key:
        return exchange

    exchange.idempotency_key = compute_idempotency_key(
        link_id=exchange.link_id,
        document_type=exchange.document_type,
        document_id=exchange.document_id,
        operation=exchange.operation,
        replay_rank=replay_rank,
    )
    champs = ["idempotency_key"]
    if not exchange.correlation_key:
        exchange.correlation_key = compute_correlation_key(
            document_type=exchange.document_type, document_id=exchange.document_id
        )
        champs.append("correlation_key")
    exchange.save(update_fields=champs)
    return exchange


def lineage(tenant_id: UUID, correlation_key: str) -> list[FlwExchange]:
    """Tous les echanges rattaches a la meme piece, du plus ancien au plus
    recent.

    C'est la reponse a « qu'est devenue cette facture ? » : la soumission
    initiale, ses reessais, le rejeu supervise qui a suivi le refus, et la
    notification entrante qui a fini par trancher. Une clef vide ne
    correle rien et renvoie une liste vide — jamais l'ensemble des
    echanges sans piece, qui n'ont aucun rapport entre eux."""
    if not correlation_key:
        return []
    return list(
        FlwExchange.objects.filter(tenant_id=tenant_id, correlation_key=correlation_key).order_by(
            "created_at"
        )
    )


__all__ = [
    "KEY_LENGTH",
    "assign_keys",
    "compute_correlation_key",
    "compute_idempotency_key",
    "lineage",
]
