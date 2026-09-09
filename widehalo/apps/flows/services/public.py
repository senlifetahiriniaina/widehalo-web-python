"""Contrat public du hub de flux — seule surface que les autres apps metier
ont le droit d'importer (cf. `tests/architecture/test_module_boundaries.py`).

**Le sens de la dependance est inverse de l'intuition, et c'est voulu.**
`flows` ne declare aucune dependance metier : c'est `accounting`, `sales` ou
`logistics` qui declareront `flows` le jour ou ils emettront un echange. Un
module metier appelle donc les fonctions ci-dessous ; le hub, lui, ne
rappelle jamais un module metier — il rend un resultat, et l'appelant en
fait ce qu'il veut.

Consequence pratique pour l'appelant : il designe sa piece par un couple
`(document_type, document_id)` de son choix, jamais par un objet. Le hub ne
resoudra jamais ce couple ; il le transporte et le rend, pour que l'appelant
retrouve ses propres pieces.

A S1, la surface se limitait a la LECTURE : « poser des fonctions
d'ecriture ici avant que la machine a etats n'existe reviendrait a laisser
un appelant creer un echange dans un etat que rien ne fait avancer ». La
machine a etats (S2) et la file (S3) existent depuis, et T3 ouvre donc la
premiere ecriture : `request_reference_lookup`, l'operation OP8. La
condition posee en S1 est levee, pas contournee — un echange cree par
cette fonction part en file et la vidange le fait avancer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.flows.models import FlwExchange, FlwLink
from apps.flows.operations import OP_QUERY_REFERENCE

if TYPE_CHECKING:
    from uuid import UUID

    from apps.core.models.tenant import Tenant


def list_exchanges_for_document(
    tenant: Tenant, *, document_type: str, document_id: UUID, limit: int = 20
) -> list[dict[str, Any]]:
    """Historique des echanges rattaches a UNE piece metier.

    Repond a « qu'est devenue cette facture chez le tiers ? » depuis la
    fiche de la piece, sans que le module appelant ait a connaitre
    `FlwExchange`. Renvoie des dicts primitifs, jamais l'objet ORM (regle de
    couplage n°1), tries du plus recent au plus ancien.

    Liste vide, jamais une exception, si la piece n'a jamais donne lieu a un
    echange : c'est le cas NORMAL pour l'immense majorite des pieces, pas
    une anomalie a signaler."""
    exchanges = FlwExchange.objects.filter(
        tenant=tenant, document_type=document_type, document_id=document_id
    ).order_by("-created_at")[:limit]
    return [
        {
            "id": exchange.id,
            "direction": exchange.direction,
            "operation": exchange.operation,
            "state": exchange.state,
            "attempt": exchange.attempt,
            "result_code": exchange.result_code,
            "correlation_key": exchange.correlation_key,
            "sent_at": exchange.sent_at,
            "settled_at": exchange.settled_at,
        }
        for exchange in exchanges
    ]


def count_exchanges_awaiting_verdict(tenant: Tenant) -> int:
    """Nombre d'echanges partis dont le tiers n'a pas encore tranche.

    Chiffre destine a la console de flux et au tableau de bord : c'est le
    seul etat ou l'entreprise a fait sa part et attend quelqu'un d'autre.
    Le distinguer de « en echec » evite de presenter comme une panne ce qui
    est un delai normal chez l'administration ou la banque."""
    return FlwExchange.objects.filter(
        tenant=tenant, state=FlwExchange.STATE_AWAITING_VERDICT
    ).count()


def has_active_link(tenant: Tenant, *, connector_code: str) -> bool:
    """`True` si ce tenant a une liaison ACTIVE sur ce connecteur.

    Permet a un module metier de n'afficher une action d'envoi que lorsque
    le canal existe reellement, plutot que de proposer un bouton qui
    echouera. C'est la liaison qui est interrogee, jamais le connecteur :
    sur une instance multi-societes, deux tenants branches sur le meme
    adaptateur ont deux enrolements independants."""
    return FlwLink.objects.filter(
        tenant=tenant, connector__code=connector_code, state=FlwLink.STATE_ACTIVE
    ).exists()


def request_reference_lookup(
    tenant: Tenant,
    *,
    connector_code: str,
    document_type: str,
    document_id: UUID,
    body: str = "",
    occurrence: str = "",
) -> dict[str, Any] | None:
    """OP8 — demande au hub d'interroger un referentiel, et rend la main.

    **Le cahier decrit OP8 comme « synchrone », et il ne peut pas l'etre
    ici.** §4.1 : « Interroger un referentiel | Sortant, lecture |
    Synchrone | Verifier un identifiant fiscal [...] | Mise en cache avec
    duree de validite, degradation en valeur saisie si le tiers ne repond
    pas ». Deux regles deja tenues l'interdisent telle quelle : aucun
    module metier n'emet d'appel reseau (regle de couplage n°1, garde CI
    depuis S6), et l'echec d'un tiers ne bloque jamais une transition
    metier (FLX-2).

    La lecture retenue : la demande part EN FILE, et le resultat ANNOTE la
    piece quand il arrive. La valeur saisie reste autoritative tant qu'elle
    n'est pas contredite — c'est exactement ce que « degradation en valeur
    saisie » decrit, et c'est la seule lecture compatible avec les deux
    regles. Creer un tiers ne dependra jamais de la latence d'un
    referentiel.

    Rend `None` quand aucune liaison active ne sert ce connecteur : ne pas
    avoir branche de referentiel est un etat parfaitement normal, pas une
    erreur a signaler. L'appelant continue avec la valeur saisie.

    **`occurrence` n'est pas facultatif pour une INTERROGATION, et le
    defaut qu'il ferme a deja coute une fois.** La clef d'idempotence se
    calcule sur (liaison, piece, operation, rang de rejeu) : pour une meme
    piece sur une meme liaison, elle NE CHANGE PAS. C'est exactement ce
    qu'il faut pour une soumission — deux tentatives du meme envoi portent
    la meme clef (FLX-4) — et c'est faux pour une lecture, qu'on refait
    legitimement plus tard : la seconde demande heurterait
    `uniq_flw_exchange_idempotency_key` par une `IntegrityError`, et le
    travail periodique qui la porte mourrait au deuxieme passage, en
    silence. Le meme defaut a ete trouve au sprint S5 sur les releves
    quotidiens sans piece, et `compute_idempotency_key` porte deja
    `occurrence` pour cette raison.

    L'appelant passe donc ce qui distingue SON passage — une date, un
    numero de campagne. Le laisser vide reste correct pour une piece qui ne
    part qu'une fois."""
    from apps.flows.services.exchange import prepare_exchange
    from apps.flows.services.queue import queue_exchange

    link = (
        FlwLink.objects.filter(
            tenant=tenant, connector__code=connector_code, state=FlwLink.STATE_ACTIVE
        )
        .select_related("connector")
        .first()
    )
    if link is None:
        return None

    exchange = queue_exchange(
        prepare_exchange(
            tenant,
            link,
            operation=OP_QUERY_REFERENCE,
            document_type=document_type,
            document_id=document_id,
            body=body,
        ),
        occurrence=occurrence,
    )
    return {
        "id": exchange.id,
        "state": exchange.state,
        "operation": exchange.operation,
        "correlation_key": exchange.correlation_key,
    }


def describe_signing_certificate(tenant: Tenant, *, connector_code: str) -> dict[str, Any]:
    """T4 (EFA-8) — ce qu'un module metier peut savoir du certificat.

    **Aucune matiere secrete ne franchit cette frontiere.** Le retour porte
    un libelle, une date d'echeance, un indice deja prevu pour l'affichage
    (« se termine par 4f2a ») et deux drapeaux. La clef privee, elle, ne
    sort jamais de `apps.flows.services.signing` — c'est pourquoi la
    SIGNATURE est rendue par `sign_document` ci-dessous plutot que la clef
    par cette fonction : ce qui sort est le resultat, ce qui reste est le
    moyen.

    Premier appelant : l'ecran de facture du bloc C, qui doit alerter
    « au moins trente jours avant echeance » — un module metier ne peut pas
    alerter sur ce qu'il n'a pas le droit de lire."""
    from apps.flows.services.signing import certificate_status

    etat = certificate_status(tenant, connector_code=connector_code)
    return {
        "present": etat.present,
        "label": etat.label,
        "hint": etat.hint,
        "expires_at": etat.expires_at,
        "expired": etat.expired,
        "expiring_soon": etat.expiring_soon,
        "days_remaining": etat.days_remaining,
    }


def sign_document(tenant: Tenant, *, connector_code: str, payload: bytes) -> dict[str, Any] | None:
    """T4 (EFA-2, EFA-8) — signe des octets, ou refuse.

    Rend `None` quand aucun certificat n'est fourni : le document est alors
    produit et archive sans signature, ce qui est l'etat normal d'une
    installation sans raccordement — EFA-2 exige qu'aucune erreur ne soit
    presentee dans ce cas.

    LEVE sur un certificat perime, parce que le critere l'exige (« une
    signature avec certificat expire est refusee AVANT soumission ») et
    parce que les deux situations n'ont rien de commun : « pas encore
    equipe » n'appelle aucune action, « equipe d'un moyen sans valeur » en
    appelle une tout de suite."""
    from apps.flows.services.signing import sign_payload

    signature = sign_payload(tenant, connector_code=connector_code, payload=payload)
    if signature is None:
        return None
    return {
        "algorithm": signature.algorithm,
        "value": signature.value,
        "certificate_hint": signature.certificate_hint,
        "signed_at": signature.signed_at,
    }


def submit_document_for_verdict(
    tenant: Tenant,
    *,
    connector_code: str,
    document_type: str,
    document_id: UUID,
    body: str,
    retain_until: Any = None,
) -> dict[str, Any] | None:
    """T4 (EFA-2) — met une piece en file pour validation par un tiers.

    **Pourquoi cette fonction existe, et ce qu'elle repare.** Le module
    `accounting` mettait en file en important lui-meme `flows.models` et
    `flows.services.queue` — ce que la regle de couplage n°1 interdit, et
    que la garde `test_module_boundaries` a refuse. Un module metier n'a
    pas a connaitre `FlwLink`, `prepare_exchange` ni la machine a etats du
    hub : il a une piece a faire valider, et c'est tout ce qu'il doit
    savoir dire.

    Rend `None` quand aucune liaison ACTIVE ne sert ce connecteur — le
    mode d'attente d'EFA-2, ou « le document est produit, signe, archive
    et mis en file ; aucune erreur n'est presentee a l'utilisateur ». Ne
    pas avoir de raccordement n'est pas une panne.

    `retain_until` porte la duree d'archivage reglementaire, que seul
    l'appelant connait (elle vient de son profil pays, EFA-7). La colonne
    existait sur `FlwPayload` depuis S1 en attendant ce premier
    appelant."""
    from apps.flows.operations import OP_SUBMIT_FOR_VERDICT
    from apps.flows.services.exchange import prepare_exchange
    from apps.flows.services.queue import queue_exchange

    link = _active_link(tenant, connector_code)
    if link is None:
        return None

    exchange = queue_exchange(
        prepare_exchange(
            tenant,
            link,
            operation=OP_SUBMIT_FOR_VERDICT,
            document_type=document_type,
            document_id=document_id,
            body=body,
            retain_until=retain_until,
        )
    )
    return {
        "id": exchange.id,
        "state": exchange.state,
        "operation": exchange.operation,
        "correlation_key": exchange.correlation_key,
    }


def activate_link(tenant: Tenant, *, connector_code: str) -> bool:
    """Ouvre le raccordement d'un connecteur pour ce tenant.

    **C'est la confirmation initiale qu'EFA-3 tolere** : « sans
    intervention manuelle autre que la confirmation initiale ». Le rejeu
    de la file, lui, suit sans qu'on le demande — mais il appartient au
    module metier, qui seul sait ce qu'il avait mis en attente.

    Rend `True` si une liaison a change d'etat, `False` si elle etait deja
    active ou n'existe pas. Une liaison deja active n'est pas une erreur :
    rejouer la file d'un raccordement deja ouvert est exactement ce qu'on
    veut pouvoir faire apres un incident, et refuser obligerait a
    suspendre puis rouvrir pour rattraper un retard."""
    link = (
        FlwLink.objects.filter(tenant=tenant, connector__code=connector_code)
        .exclude(state=FlwLink.STATE_ACTIVE)
        .first()
    )
    if link is None:
        return False
    link.state = FlwLink.STATE_ACTIVE
    link.save(update_fields=["state"])
    return True


def initiate_payment(
    tenant: Tenant,
    *,
    connector_code: str,
    document_type: str,
    document_id: UUID,
    body: str,
    occurrence: str,
) -> dict[str, Any] | None:
    """T5 (PAY-1) — met une intention de reglement en file (OP5).

    **Pourquoi elle existe.** `accounting` doit demander un mouvement
    d'argent a un tiers ; la regle de couplage n°1 lui interdit d'emettre
    l'appel lui-meme, et de connaitre `FlwLink`, `prepare_exchange` ou la
    machine a etats. Il a une piece et un montant, et c'est tout ce qu'il
    doit savoir dire — meme forme que `submit_document_for_verdict` au lot
    T4, pour la meme raison.

    **`occurrence` est OBLIGATOIRE ici, et c'est le meme defaut que T3 a
    paye une fois.** La clef d'idempotence se calcule sur (liaison, piece,
    operation, rang de rejeu, occurrence) : pour une meme facture sur une
    meme liaison, elle NE CHANGE PAS. Une facture peut pourtant donner lieu
    a plusieurs intentions successives — la premiere expire sans etre
    payee, le payeur en redemande une —, et la seconde emission heurterait
    alors `uniq_flw_exchange_idempotency_key` par une `IntegrityError`.
    C'est exactement ce qui faisait mourir la commande nocturne d'OP8 au
    deuxieme passage.

    L'appelant passe donc ce qui distingue SON emission : la reference
    externe de l'intention, qui est unique par tenant et que nous emettons
    nous-memes. Deux emissions de LA MEME intention gardent la meme clef —
    et c'est bien ce qu'on veut : re-emettre une intention deja transmise
    est le double debit que PAY-7 interdit, et la base le refuse.

    **Ce qui protege du double debit n'est donc pas cette clef seule** :
    c'est la regle metier de `create_payment_intent`, qui refuse une
    seconde intention vivante sur la meme piece. Une contrainte de base
    qui remonterait en 500 ne serait pas une protection, seulement une
    panne mieux placee.

    Rend `None` quand aucune liaison ACTIVE ne sert ce connecteur. Ne pas
    avoir de raccordement d'encaissement est l'etat de toute installation
    qui encaisse au comptoir, pas une panne."""
    from apps.flows.operations import OP_INITIATE_PAYMENT
    from apps.flows.services.exchange import prepare_exchange
    from apps.flows.services.queue import queue_exchange

    link = _active_link(tenant, connector_code)
    if link is None:
        return None

    exchange = queue_exchange(
        prepare_exchange(
            tenant,
            link,
            operation=OP_INITIATE_PAYMENT,
            document_type=document_type,
            document_id=document_id,
            body=body,
        ),
        occurrence=occurrence,
    )
    return {
        "id": exchange.id,
        "state": exchange.state,
        "operation": exchange.operation,
        "correlation_key": exchange.correlation_key,
    }


def correlate_inbound_exchange(
    tenant: Tenant, *, exchange_id: Any, document_type: str, document_id: UUID
) -> str:
    """T5 — rattache un echange ENTRANT a la piece qu'il concerne.

    **Le defaut que cette fonction ferme, et il rendait faux le seul
    service que la clef existe pour rendre.** `FlwExchange.correlation_key`
    est documentee ainsi : « relie l'echange sortant, la notification
    entrante qui lui repond et la piece — c'est elle qui permet de
    repondre a "qu'est devenue cette facture ?" sans parcourir trois
    journaux ». Or `assign_keys` ne pose la clef qu'a la MISE EN FILE,
    c'est-a-dire sur le seul chemin sortant : tout echange entrant ecrit
    par `receive_event` naissait donc avec une clef VIDE. `lineage()`
    rendait la soumission et ses reessais, et jamais la notification qui
    les a tranches — la seule des trois qui dise ce que la facture est
    DEVENUE.

    **Pourquoi c'est l'appelant metier qui la pose, et pas le hub.** Le
    hub ne lit jamais le corps d'un echange : il transporte une charge
    utile opaque, et lui faire deviner a quelle piece elle se rapporte
    reviendrait a lui faire connaitre le format de chaque tiers. C'est le
    module metier qui a corrèle — par une reference QU'IL A EMISE — et lui
    seul peut nommer la piece sans deviner.

    **La PIECE est posee en meme temps que la clef, et l'oublier ne
    corrigeait le defaut qu'a moitie.** Une premiere redaction n'ecrivait
    que `correlation_key`. `lineage()` rendait alors bien les deux
    echanges — mais `list_exchanges_for_document`, qui interroge
    `document_type`/`document_id` et non la clef, n'en rendait qu'un. Or
    c'est CETTE fonction-la que le fragment d'ecran de CON-1 appelle depuis
    la fiche d'une piece : « depuis toute piece metier, l'etat de ses
    echanges est atteignable en un clic ». La facture aurait affiche la
    demande partie, jamais le paiement recu. Mesure faite par le test de
    bout en bout, en comparant les deux lectures — aucune des deux seule ne
    le montrait.

    **Un echange deja rattache n'est jamais deplace**, et la valeur
    existante est rendue. Deplacer un echange d'une lignee vers une autre
    reecrirait l'histoire d'une piece a laquelle il a reellement
    appartenu ; et une seconde distribution du meme evenement par le bus —
    qui reessaie trois fois — ne doit rien changer.

    Rend la clef effectivement portee par l'echange, ou la chaine vide si
    l'echange est introuvable ou sortant."""
    from apps.flows.services.idempotency import compute_correlation_key

    exchange = FlwExchange.objects.filter(
        tenant=tenant, id=exchange_id, direction=FlwExchange.DIRECTION_INBOUND
    ).first()
    if exchange is None:
        return ""
    if exchange.correlation_key:
        return exchange.correlation_key

    exchange.correlation_key = compute_correlation_key(
        document_type=document_type, document_id=document_id
    )
    exchange.document_type = document_type
    exchange.document_id = document_id
    exchange.save(update_fields=["correlation_key", "document_type", "document_id"])
    return exchange.correlation_key


def publish_dataset(
    tenant: Tenant,
    *,
    connector_code: str,
    body: str,
    occurrence: str,
    document_type: str = "",
    document_id: UUID | None = None,
) -> dict[str, Any] | None:
    """T7 (COM-3) — publie un jeu de donnees chez un tiers (OP2).

    **Le vide que cette fonction ferme.** `OP_PUBLISH_DATASET` appartient au
    jeu ferme des huit operations depuis S1, l'adaptateur de reference sait
    la servir — et AUCUNE fonction de la surface publique ne permettait de
    la demander. Exactement le meme vide qu'`initiate_payment` avant le bloc
    D : une operation declaree que personne ne pouvait invoquer.

    **`occurrence` est obligatoire, et c'est la troisieme fois que ce defaut
    se presente.** Une publication de disponibilite se REFAIT — toutes les
    heures, a chaque mouvement de stock. Sans occurrence, la clef
    d'idempotence serait constante et la seconde publication heurterait
    `uniq_flw_exchange_idempotency_key` par une `IntegrityError` : la
    planification mourrait au deuxieme passage, en silence. C'est le defaut
    paye par OP8 au lot T3, puis retrouve sur OP5 au lot T5.

    **`document_type`/`document_id` restent facultatifs**, et c'est ce qui
    distingue OP2 des autres : un catalogue publie ne se rattache a aucune
    piece metier. La correlation reste vide, ce que
    `compute_correlation_key` traite deja explicitement — « correler ce qui
    ne se rattache a rien produirait des grappes d'echanges sans lien entre
    eux »."""
    from apps.flows.operations import OP_PUBLISH_DATASET
    from apps.flows.services.exchange import prepare_exchange
    from apps.flows.services.queue import queue_exchange

    link = _active_link(tenant, connector_code)
    if link is None:
        return None

    exchange = queue_exchange(
        prepare_exchange(
            tenant,
            link,
            operation=OP_PUBLISH_DATASET,
            document_type=document_type,
            document_id=document_id,
            body=body,
        ),
        occurrence=occurrence,
    )
    return {
        "id": exchange.id,
        "state": exchange.state,
        "operation": exchange.operation,
        "correlation_key": exchange.correlation_key,
    }


def has_settled_reference_lookup(
    tenant: Tenant, *, document_type: str, document_id: UUID, since: Any = None
) -> bool:
    """T5 (PAY-7) — une interrogation de referentiel a-t-elle recu sa reponse ?

    **Pourquoi cette fonction plutot qu'une lecture chez l'appelant.** Le
    module metier a besoin de savoir si le tiers a repondu avant de
    re-emettre une demande de paiement. Il a d'abord ete ecrit qu'il lise
    lui-meme la liste des echanges et compare `operation` a `OP8` et
    `state` a `accepte` — ce qui lui faisait importer `flows.models` et
    `flows.operations`, et la garde de couplage l'a refuse. Elle a raison :
    un module metier qui connait le nom de nos etats se casse le jour ou
    la machine a etats change, sans que rien ne le previenne.

    La question posee ici est donc formulee dans les termes de l'appelant —
    « ai-je une reponse ? » — et c'est le hub qui sait ce qu'« avoir une
    reponse » veut dire.

    `since` ecarte les reponses ANTERIEURES a ce qu'on interroge : une piece
    peut donner lieu a plusieurs demandes successives, et la reponse
    obtenue pour la precedente ne dit rien de celle-ci."""
    from apps.flows.operations import OP_QUERY_REFERENCE

    lectures = FlwExchange.objects.filter(
        tenant=tenant,
        document_type=document_type,
        document_id=document_id,
        operation=OP_QUERY_REFERENCE,
        state=FlwExchange.STATE_ACCEPTED,
    )
    if since is not None:
        lectures = lectures.filter(settled_at__gte=since)
    return lectures.exists()


def _active_link(tenant: Tenant, connector_code: str) -> FlwLink | None:
    """La liaison ACTIVE servant ce connecteur, ou `None`.

    C'est la LIAISON qui est interrogee, jamais le connecteur seul : sur
    une instance multi-societes, deux tenants branches sur le meme
    adaptateur ont deux enrolements independants."""
    return (
        FlwLink.objects.filter(
            tenant=tenant, connector__code=connector_code, state=FlwLink.STATE_ACTIVE
        )
        .select_related("connector")
        .first()
    )


def read_inbound_payload(tenant: Tenant, *, exchange_id: Any) -> str | None:
    """T5 — le corps d'un echange ENTRANT, pour le module qui doit le lire.

    **Le chemin entrant s'arretait ici.** `receive_event` ecrivait un
    echange et sa charge utile ; aucun module metier ne pouvait les lire,
    parce que la surface publique n'exposait que des LISTES d'echanges —
    etat, horodatage, clef de correlation — jamais le contenu. Une
    notification de paiement arrivait donc, etait tracee, et restait
    illisible.

    **Seulement un echange ENTRANT.** Rendre le corps d'un echange sortant
    n'apprendrait rien a personne — c'est le module metier qui l'a
    construit — et ouvrirait une lecture dont aucun critere n'a besoin.

    Rend `None` quand la charge utile a ete purgee (FLX-5) : c'est un etat
    NORMAL, pas une erreur. L'echange reste, son empreinte aussi ; il n'y
    a simplement plus rien a lire, et l'appelant doit pouvoir le
    distinguer d'un echange introuvable — les deux rendent `None`, et
    aucun des deux n'est un incident."""
    from apps.flows.models import FlwPayload

    payload = (
        FlwPayload.objects.filter(
            tenant=tenant,
            exchange_id=exchange_id,
            exchange__direction=FlwExchange.DIRECTION_INBOUND,
        )
        .only("body")
        .first()
    )
    return payload.body if payload is not None else None


__all__ = [
    "activate_link",
    "correlate_inbound_exchange",
    "count_exchanges_awaiting_verdict",
    "describe_signing_certificate",
    "has_active_link",
    "has_settled_reference_lookup",
    "initiate_payment",
    "list_exchanges_for_document",
    "publish_dataset",
    "read_inbound_payload",
    "request_reference_lookup",
    "sign_document",
    "submit_document_for_verdict",
]
