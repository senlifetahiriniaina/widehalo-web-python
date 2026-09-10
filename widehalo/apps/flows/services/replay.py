"""S4 — le rejeu supervise.

Le cahier (§13.4) tient en trois phrases, et chacune interdit quelque chose
de precis :

« **Toujours humain, jamais automatique** au-dela de la politique d'echec
configuree. » Le reessai automatique s'arrete ou l'axe A5 le dit ; ce qui
suit demande une decision. Un rejeu declenche par une tache planifiee
serait un quatrieme reessai deguise, et le plafond de tentatives ne
voudrait plus rien dire.

« Le panneau de rejeu affiche le **volume et le cout estime avant
confirmation**. » §10.2 en donne le motif : « le rejeu de masse sans
estimation est la premiere cause de facture surprise ». D'ou
`estimate_replay`, qui existe pour etre appele AVANT — et dont le resultat
n'engage rien.

« Un rejeu **cree de nouveaux echanges, il ne reecrit jamais les
anciens** : l'historique des tentatives est la piece qui explique une
facture de tiers. » C'est l'inverse exact du seul precedent du depot :
`core/management/commands/replay_events.py` remet `attempts = 0` sur la
ligne existante et la redispatche. Ce patron convient a un evenement
interne, dont l'historique n'a aucune valeur opposable ; il ne convient
pas ici, ou le registre EST la preuve.

**Ce que « successeur » veut dire concretement.** Le nouvel echange porte
la meme piece, la meme liaison, la meme operation, la meme clef de
correlation — et une clef d'idempotence NEUVE. C'est cette derniere
difference qui fait toute l'affaire : donner au successeur la clef de son
predecesseur ferait ignorer la resoumission par le tiers, soit l'inverse de
ce que l'exploitant vient de demander.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils.translation import gettext as _

from apps.flows.models import FlwExchange
from apps.flows.services.exchange import prepare_exchange, transition_exchange
from apps.flows.services.idempotency import assign_keys

if TYPE_CHECKING:
    from collections.abc import Sequence
    from uuid import UUID

    from apps.core.models.tenant import Tenant

#: Les etats depuis lesquels un rejeu supervise a un sens. `EN_ECHEC` est
#: le puits — nous avons renonce ; `A_REESSAYER` sans echeance est la mise
#: en attente de l'axe A5 — les tentatives sont epuisees et l'echange
#: attend precisement une decision humaine.
#:
#: `ACCEPTE` et `REJETE` en sont ABSENTS, et c'est l'invariant 1 : le tiers
#: a tranche. Rejouer un echange accepte creerait un doublon chez lui ; en
#: rejouer un rejete sans avoir corrige la piece reproduirait le refus.
REPLAYABLE_STATES = (FlwExchange.STATE_FAILED, FlwExchange.STATE_TO_RETRY)


@dataclass(frozen=True)
class ReplayEstimate:
    """Ce que l'ecran doit afficher AVANT que quiconque ne confirme."""

    count: int
    cost_ariary: Decimal
    unpriced_count: int
    units: frozenset[str]

    @property
    def is_cost_certain(self) -> bool:
        """Faux des qu'un echange de la selection n'a pas de cout impute.

        La nuance n'est pas cosmetique : annoncer « 12 000 Ar » pour une
        selection dont la moitie n'est pas tarifee, c'est annoncer un
        plancher en le presentant comme un total. L'ecran doit dire « au
        moins », et cette propriete est ce qui le lui permet."""
        return self.unpriced_count == 0


def replayable_exchanges(tenant: Tenant, *, ids: Sequence[UUID]) -> list[FlwExchange]:
    """Les echanges de la selection qui peuvent effectivement etre rejoues.

    Filtre plutot que de lever : une selection faite a l'ecran peut
    contenir une ligne qu'un autre utilisateur vient de rejouer, et faire
    echouer l'operation entiere pour cela obligerait a recommencer la
    selection. Ce qui a ete ecarte est visible par difference entre le
    nombre demande et le nombre rendu."""
    return list(
        FlwExchange.objects.filter(
            tenant=tenant, id__in=list(ids), state__in=REPLAYABLE_STATES
        ).select_related("link")
    )


def estimate_replay(tenant: Tenant, *, ids: Sequence[UUID]) -> ReplayEstimate:
    """Le volume et le cout estime, sans rien engager.

    Le cout retenu est celui des echanges d'ORIGINE : c'est la meilleure
    estimation disponible, et la seule honnete — le tarif du successeur
    n'existe pas encore, il sera impute a l'envoi. Presenter autre chose
    supposerait de connaitre une grille que ce module n'a pas le droit de
    connaitre (« aucun tarif n'est ecrit dans le code »)."""
    selection = FlwExchange.objects.filter(
        tenant=tenant, id__in=list(ids), state__in=REPLAYABLE_STATES
    )
    total = selection.exclude(cost_ariary__isnull=True).aggregate(t=Sum("cost_ariary"))["t"]
    return ReplayEstimate(
        count=selection.count(),
        cost_ariary=total or Decimal(0),
        unpriced_count=selection.filter(cost_ariary__isnull=True).count(),
        units=frozenset(
            selection.exclude(cost_unit="").values_list("cost_unit", flat=True).distinct()
        ),
    )


def replay_exchange(exchange: FlwExchange, *, replay_rank: int | None = None) -> FlwExchange:
    """Cree le SUCCESSEUR d'un echange, et le met en file.

    Refuse un echange que le tiers a tranche : `ACCEPTE` produirait un
    doublon chez lui, `REJETE` reproduirait le refus tant que la piece n'a
    pas ete corrigee — et corriger la piece produit un echange NEUF par le
    chemin ordinaire, pas un rejeu.

    Le rang de rejeu est deduit de la lignee quand il n'est pas fourni :
    c'est lui qui fait differer la clef d'idempotence du successeur de
    celle de son predecesseur. Le calculer a chaque fois plutot que de le
    stocker evite un compteur de plus a tenir a jour — la lignee le porte
    deja."""
    if exchange.state not in REPLAYABLE_STATES:
        raise ValidationError(
            _(
                "Échange %(id)s dans l'état %(state)s : seuls un échec ou une mise en "
                "attente se rejouent. Un verdict du tiers ne se rejoue pas — il donne "
                "lieu à un nouvel envoi après correction de la pièce."
            )
            % {"id": exchange.id, "state": exchange.state}
        )

    rang = replay_rank
    if rang is None:
        rang = (
            FlwExchange.objects.filter(
                tenant_id=exchange.tenant_id,
                # La clef de correlation est transmise EXPLICITEMENT, et
                # `assign_keys` saurait pourtant la recalculer depuis la piece.
                # Cette redondance est deliberee et il vaut mieux l'ecrire :
                # deux chemins independants portent la lignee, si bien qu'aucune
                # falsification d'UN SEUL des deux ne la rompt — il a fallu les
                # muter tous les deux pour voir le test rougir. Le chemin
                # explicite couvre le cas ou la piece est absente (une
                # correlation posee a la main par un rappel de tiers) ; le
                # recalcul couvre le cas ou elle est presente et le successeur
                # cree par un autre chemin.
                correlation_key=exchange.correlation_key,
                document_id=exchange.document_id,
            ).count()
            if exchange.correlation_key
            else 1
        )

    with transaction.atomic():
        successeur = prepare_exchange(
            exchange.tenant,
            exchange.link,
            operation=exchange.operation,
            direction=exchange.direction,
            document_type=exchange.document_type,
            document_id=exchange.document_id,
            correlation_key=exchange.correlation_key,
        )
        # L'empreinte du predecesseur est reportee : le successeur rejoue
        # LE MEME contenu. La recalculer depuis une charge utile absente
        # (purgee, FLX-5) donnerait une empreinte vide et ferait croire que
        # le contenu a change.
        successeur.payload_fingerprint = exchange.payload_fingerprint
        successeur.save(update_fields=["payload_fingerprint"])
        assign_keys(successeur, replay_rank=rang)
        transition_exchange(successeur, to_state=FlwExchange.STATE_QUEUED)

    return successeur


def replay_selection(
    tenant: Tenant, *, ids: Sequence[UUID], acknowledged: ReplayEstimate
) -> list[FlwExchange]:
    """Rejoue une selection, et renvoie les successeurs crees.

    Chaque echange est rejoue dans SA propre transaction (celle de
    `replay_exchange`) : une selection de deux cents lignes dont une
    echoue ne doit pas annuler les cent quatre-vingt-dix-neuf autres, sans
    quoi l'exploitant recommencerait indefiniment une operation qui
    reussit presque.

    **T9 (CON-4) — `acknowledged` est OBLIGATOIRE, et c'est tout le
    critere.** « Le panneau de rejeu affiche volume et cout estime avant
    confirmation ; **aucun rejeu de masse n'est declenchable sans cette
    estimation**. »

    Faire porter cette regle a l'ecran seul l'aurait rendue contournable en
    appelant cette fonction — exactement la faiblesse refusee pour la garde
    d'activation. L'estimation vue est donc PASSEE ICI, et confrontee a
    l'estimation courante : si la selection a change entre l'affichage et la
    confirmation, les chiffres ne correspondent plus et le rejeu est refuse.
    C'est ce qui distingue une estimation opposable d'un chiffre affiche.

    Le rejeu d'UN echange isole passe par `replay_exchange` et n'a pas
    besoin de panneau : le §15.2 vise « tout rejeu ou envoi GROUPE », et
    demander une estimation pour une ligne unique ferait d'une protection
    contre la facture surprise une formalite."""
    courant = estimate_replay(tenant, ids=ids)
    if (acknowledged.count, acknowledged.cost_ariary) != (courant.count, courant.cost_ariary):
        raise ValidationError(
            _(
                "La sélection a changé depuis l'estimation affichée "
                "(%(vus)d échange(s) pour %(cout_vu)s Ar, désormais %(reels)d pour "
                "%(cout_reel)s Ar). Le rejeu est refusé : une estimation périmée "
                "n'est plus une estimation."
            )
            % {
                "vus": acknowledged.count,
                "cout_vu": acknowledged.cost_ariary,
                "reels": courant.count,
                "cout_reel": courant.cost_ariary,
            }
        )

    successeurs = []
    for exchange in replayable_exchanges(tenant, ids=ids):
        successeurs.append(replay_exchange(exchange))
    return successeurs


__all__ = [
    "REPLAYABLE_STATES",
    "ReplayEstimate",
    "estimate_replay",
    "replay_exchange",
    "replay_selection",
    "replayable_exchanges",
]
