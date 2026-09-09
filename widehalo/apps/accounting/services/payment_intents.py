"""T5 (bloc D, PAY-1 et PAY-7) — émettre une demande de règlement, et ne
jamais la ré-émettre à l'aveugle.

**Ce que ce fichier ferme.** `AccPaymentIntent` existait, avec sa
contrainte d'unicité et sa docstring, et **rien ne créait d'intention** :
la corrélation de `payment_settlement` cherchait donc une intention que
personne n'écrivait, et le chemin nominal de PAY-2 était inatteignable par
construction. Le défaut est celui que ce chantier rencontre à chaque lot —
un objet complet, documenté, sans producteur.

**La référence est ÉMISE PAR NOUS, et c'est ce qui rend la corrélation
opposable.** C'est le point le plus important du lot, et il décide de ce
qui a le droit de produire une écriture automatique. L'interdit du §4.3
autorise l'automatisme quand « une règle métier déjà éprouvée dispose », et
refuse le rapprochement par similarité. Une référence que nous avons
générée, transmise au payeur, et que l'opérateur nous renvoie telle quelle,
n'est pas une ressemblance : c'est une clef. Si elle venait du tiers, la
retrouver dans nos livres serait une devinette, et l'écriture automatique
n'aurait aucun fondement.

**Le double débit ne se protège pas par une contrainte de base.** La
contrainte `uniq_acc_payment_intent_external_reference` empêche deux
intentions de revendiquer la même référence — mais deux intentions
successives sur la même facture portent deux références différentes, et
elle ne les voit pas. Ce qui protège est la règle écrite ici : tant qu'une
intention peut encore être payée, aucune seconde n'est émise. Une
contrainte qui remonterait en 500 ne serait pas une protection, seulement
une panne mieux placée.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting.models import AccPaymentIntent, AccPaymentNotification
from apps.accounting.services.payment_providers import resolve_tenant_provider

#: Le connecteur qui sert l'encaissement mobile. Importé depuis l'abonné
#: plutôt que recopié : les deux moitiés de la chaîne — ce qui émet et ce
#: qui reçoit — doivent désigner le MÊME raccordement, et deux chaînes
#: recopiées finissent par diverger d'un caractère.
from apps.accounting.services.payment_registration import CONNECTOR_CODE

if TYPE_CHECKING:
    from uuid import UUID

    from apps.core.models.tenant import Tenant

#: Le préfixe des références que nous émettons. Il sert à l'exploitant qui
#: lit un relevé d'opérateur : une ligne préfixée est une transaction que
#: nous avons initiée, une ligne sans préfixe vient d'ailleurs (un paiement
#: au comptoir saisi par un vendeur, par exemple) et n'a aucune raison de
#: corréler.
REFERENCE_PREFIX = "WH"

logger = logging.getLogger(__name__)

#: Combien de temps une demande de règlement reste payable.
#:
#: **Réserve.** Aucun opérateur visé ne publie de durée de validité
#: contractuelle accessible à ce dépôt — même réserve que
#: `payment_providers` et `mobile_money`. 72 heures est une valeur de
#: paramétrage, pas une règle : elle est lue par `reemit_intent`, qui
#: refuse de remplacer une intention encore payable, et c'est le seul
#: endroit où elle décide de quelque chose.
INTENT_VALIDITY_HOURS = 72

#: Les états dans lesquels une intention peut encore recevoir un paiement.
#: Écrit en positif et nommé, parce que trois lecteurs s'en servent et
#: qu'un `state in ("creee", "transmise")` recopié trois fois est le début
#: d'une divergence.
LIVE_STATES = frozenset({AccPaymentIntent.STATE_CREATED, AccPaymentIntent.STATE_SENT})

#: Ce qu'il est advenu d'une demande de ré-émission. Nommé plutôt que
#: booléen : « déjà réglée », « une notification est déjà arrivée » et
#: « l'état a été demandé au tiers » appellent trois phrases différentes à
#: l'écran, et un `False` commun aux trois n'en dirait aucune.
REEMIT_SETTLED = "deja_reglee"
REEMIT_NOTIFIED = "notification_deja_recue"
REEMIT_STILL_PAYABLE = "encore_payable"
REEMIT_QUERY_SENT = "etat_demande_au_tiers"
REEMIT_CANNOT_ASK = "tiers_injoignable"
REEMIT_REPLACED = "remplacee"


@dataclass(frozen=True)
class ReemitResult:
    """Ce qui a été fait, et l'intention neuve s'il y en a une."""

    outcome: str
    intent: AccPaymentIntent | None = None

    @property
    def emitted_again(self) -> bool:
        """Vrai UNIQUEMENT quand une seconde demande est réellement partie
        chez le payeur. C'est la propriété que la falsification du double
        débit interroge : aucun autre `outcome` ne peut la rendre vraie."""
        return self.outcome == REEMIT_REPLACED


def create_payment_intent(
    tenant: Tenant,
    *,
    document_type: str,
    document_id: UUID,
    amount: Decimal,
    currency: str = "MGA",
    now: dt.datetime | None = None,
) -> AccPaymentIntent:
    """Émet une demande de règlement pour une pièce, et la transmet.

    **PAY-1, et les deux moitiés du critère.** « Le basculement d'un tenant
    entre agrégateur et raccordement direct s'effectue par paramètre, sans
    modification de code et sans reprise des intentions en cours. » La voie
    est donc lue sur le tenant à la création — jamais un `if` par
    fournisseur — et **écrite dans l'intention**, pour qu'un basculement de
    ce matin ne rende pas orphelines les intentions parties hier.

    **Une seule intention vivante par pièce.** Rappelée sur une pièce qui
    en porte déjà une, pour le même montant, elle REND CELLE-LÀ plutôt que
    d'en créer une seconde : un double clic sur un bouton « demander le
    paiement » ne doit pas produire deux demandes que le payeur pourrait
    honorer toutes les deux. Pour un montant différent, elle refuse — le
    silence serait pire que le refus, puisqu'il faudrait choisir entre
    réclamer l'ancien montant au payeur et risquer le double débit ; c'est
    à l'appelant d'annuler explicitement.

    **L'absence de raccordement n'est pas une erreur.** Sans liaison
    active, l'intention est créée et reste `creee` : elle porte sa
    référence, elle est visible, et elle repartira quand le raccordement
    ouvrira. C'est la même posture que le mode d'attente d'EFA-2, et pour
    la même raison — une installation qui n'a pas encore branché son
    opérateur n'est pas en panne."""
    maintenant = now or timezone.now()
    montant = Decimal(amount)
    if montant <= 0:
        raise ValidationError(
            _(
                "Une demande de règlement porte un montant strictement positif ; "
                "%(montant)s ne demanderait rien à personne."
            )
            % {"montant": montant}
        )

    voie = resolve_tenant_provider(tenant)
    if voie is None:
        raise ValidationError(
            _(
                "Aucune voie d'encaissement mobile n'est configurée pour cette "
                "société. Le choix se fait par paramètre (agrégateur ou "
                "raccordement direct) ; sans lui, aucune demande ne peut partir."
            )
        )

    existante = (
        AccPaymentIntent.objects.filter(
            tenant=tenant,
            document_type=document_type,
            document_id=document_id,
            state__in=LIVE_STATES,
        )
        .order_by("-created_at")
        .first()
    )
    if existante is not None:
        if existante.amount == montant and existante.currency == currency:
            return existante
        raise ValidationError(
            _(
                "Une demande de règlement de %(ancien)s %(devise)s est déjà en "
                "cours sur cette pièce. En émettre une seconde pour "
                "%(nouveau)s exposerait au double débit : annulez la première, "
                "ou attendez son échéance."
            )
            % {
                "ancien": existante.amount,
                "devise": existante.currency,
                "nouveau": montant,
            }
        )

    with transaction.atomic():
        intention = AccPaymentIntent.objects.create(
            tenant=tenant,
            document_type=document_type,
            document_id=document_id,
            provider_code=voie.code,
            amount=montant,
            currency=currency,
            expires_at=maintenant + dt.timedelta(hours=INTENT_VALIDITY_HOURS),
        )
        # La référence dérive de la clef primaire, posée par la base : elle
        # est donc unique par construction, et non par une séquence qu'il
        # faudrait verrouiller. Écrite en second temps parce que l'identité
        # n'existe qu'après l'insertion — la contrainte d'unicité exclut
        # explicitement la chaîne vide pour rendre cet intervalle légal.
        intention.external_reference = f"{REFERENCE_PREFIX}-{intention.id.hex.upper()}"
        intention.save(update_fields=["external_reference"])

    _transmit(tenant, intention)
    return intention


def reemit_intent(intention: AccPaymentIntent, *, now: dt.datetime | None = None) -> ReemitResult:
    """PAY-7 — ne redemande jamais un paiement sans savoir où en est le premier.

    **Le critère** : « aucun double débit n'est possible ». Une intention
    ré-émise pendant que le payeur règle la première produit exactement
    cela — et l'argent est parti, il ne se reprend pas par une transaction
    de base de données.

    **Trois refus, puis une question, puis seulement le remplacement.**

    1. Déjà réglée chez nous, ou une notification déjà reçue sur sa
       référence : l'argent a bougé, il n'y a rien à redemander. La
       notification compte même ORPHELINE — orpheline veut dire « nous ne
       savons pas à quoi la rattacher », jamais « elle n'a pas eu lieu ».
    2. Encore payable — l'échéance n'est pas atteinte : le payeur a le lien
       en main, et une seconde demande serait précisément le double débit.
       C'est le seul lecteur d'`expires_at`, et c'est ce qui fait de ce
       champ autre chose qu'une décoration.
    3. Jamais transmise (aucun raccordement au moment de sa création) :
       aucun tiers n'en a jamais entendu parler, donc rien à demander.
       Elle est simplement transmise, maintenant.

    Ensuite seulement vient la question au tiers, et elle ne se répond pas
    dans le même appel : la règle de couplage n°1 interdit à `accounting`
    d'attendre un tiers, et FLX-2 interdit à un tiers de bloquer une
    transition. Le premier passage POSE la question (OP8, en file) ; le
    second, une fois la réponse arrivée par le webhook, remplace. Deux
    passages qui apprennent deux choses différentes — c'est ce qui
    distingue cette fonction d'une boucle qui tourne sans rien savoir de
    plus."""
    from apps.flows.services.public import request_reference_lookup

    maintenant = now or timezone.now()
    tenant = intention.tenant

    if intention.state == AccPaymentIntent.STATE_SETTLED:
        return ReemitResult(outcome=REEMIT_SETTLED, intent=intention)

    if (
        intention.external_reference
        and AccPaymentNotification.objects.filter(
            tenant=tenant, external_reference=intention.external_reference
        ).exists()
    ):
        return ReemitResult(outcome=REEMIT_NOTIFIED, intent=intention)

    if intention.state not in LIVE_STATES:
        # Annulée : quelqu'un a décidé qu'elle ne devait plus être payée.
        # La ressusciter contredirait cette décision.
        return ReemitResult(outcome=REEMIT_SETTLED, intent=intention)

    if intention.expires_at and maintenant < intention.expires_at:
        return ReemitResult(outcome=REEMIT_STILL_PAYABLE, intent=intention)

    if intention.state == AccPaymentIntent.STATE_CREATED:
        # Jamais partie : aucun tiers ne la connaît, il n'y a personne à
        # interroger. Elle repart telle quelle, avec sa référence, donc
        # sans créer de seconde demande.
        _transmit(tenant, intention)
        return ReemitResult(outcome=REEMIT_REPLACED, intent=intention)

    if not _state_query_answered(tenant, intention):
        demande = request_reference_lookup(
            tenant,
            connector_code=CONNECTOR_CODE,
            document_type=intention.document_type,
            document_id=intention.document_id,
            body=json.dumps(
                {"reference": intention.external_reference, "question": "etat_paiement"},
                sort_keys=True,
            ),
            occurrence=f"etat-{intention.external_reference}-{maintenant.date().isoformat()}",
        )
        if demande is None:
            return ReemitResult(outcome=REEMIT_CANNOT_ASK, intent=intention)
        return ReemitResult(outcome=REEMIT_QUERY_SENT, intent=intention)

    with transaction.atomic():
        intention.state = AccPaymentIntent.STATE_EXPIRED
        intention.save(update_fields=["state"])
        remplacante = AccPaymentIntent.objects.create(
            tenant=tenant,
            document_type=intention.document_type,
            document_id=intention.document_id,
            # La voie de l'ANCIENNE, pas celle du tenant aujourd'hui : le
            # remplacement d'une demande n'est pas le moment de changer
            # d'opérateur au dos du payeur, et PAY-1 exige qu'un
            # basculement ne reprenne pas les intentions en cours.
            provider_code=intention.provider_code,
            amount=intention.amount,
            currency=intention.currency,
            expires_at=maintenant + dt.timedelta(hours=INTENT_VALIDITY_HOURS),
        )
        remplacante.external_reference = f"{REFERENCE_PREFIX}-{remplacante.id.hex.upper()}"
        remplacante.save(update_fields=["external_reference"])

    _transmit(tenant, remplacante)
    return ReemitResult(outcome=REEMIT_REPLACED, intent=remplacante)


def _transmit(tenant: Tenant, intention: AccPaymentIntent) -> None:
    """Met l'intention en file chez le tiers, et note qu'elle est partie.

    **La charge utile ne porte aucun numéro de compte**, et ce n'est pas un
    oubli : §9.2 l.602 l'interdit nommément à `accounting` — « aucun numéro
    de compte complet dans une trace ou une charge utile archivée ». Ce qui
    part est le strict nécessaire pour qu'un payeur paie : une référence,
    un montant, une devise, une échéance.

    L'état ne passe à `transmise` que si le hub a réellement mis en file.
    Le contraire — marquer transmis ce qui n'est parti nulle part —
    ferait croire à `reemit_intent` qu'un tiers connaît cette demande, et
    lui ferait poser une question à personne."""
    from apps.accounting.models import AccPaymentIntent
    from apps.flows.services.public import initiate_payment

    try:
        # **Le `atomic()` interne n'est pas décoratif : sans lui, le
        # rattrapage ci-dessous ne rattrape rien.** PostgreSQL abandonne la
        # transaction entière au premier `IntegrityError` ; attraper
        # l'exception sans point de sauvegarde laisse la connexion en
        # « needs_rollback », et la première requête suivante — ici le
        # `save()` de l'état — lève `TransactionManagementError`. Le
        # remède serait alors plus dur à lire que le mal : une erreur
        # serveur, mais sur une autre ligne. Trouvé par le test, jamais par
        # la relecture.
        with transaction.atomic():
            accuse = initiate_payment(
                tenant,
                connector_code=CONNECTOR_CODE,
                document_type=intention.document_type,
                document_id=intention.document_id,
                body=json.dumps(_payload(intention), sort_keys=True),
                occurrence=intention.external_reference,
            )
    except IntegrityError:
        # **Cette intention est DÉJÀ partie, et c'est la seule lecture
        # possible de cette collision.** La clef d'idempotence se calcule
        # sur (liaison, pièce, opération, occurrence), et l'occurrence est
        # la référence externe — unique par société, émise par nous, propre
        # à CETTE intention. Une collision ne peut donc désigner que sa
        # propre émission précédente.
        #
        # Sans ce rattrapage, une seconde tentative de transmission
        # remonte en `IntegrityError` jusqu'à l'écran, c'est-à-dire en 500
        # sur un bouton — trouvé par le test de relance, jamais par une
        # relecture. Marquer « transmise » est ce que l'état RÉEL commande :
        # l'échange existe, il est en file, et le nier ferait redemander
        # éternellement l'état d'une demande bel et bien partie.
        logger.info(
            "intention %s déjà transmise (clef d'idempotence existante)",
            intention.external_reference,
        )
        accuse = {"deja_transmise": True}

    if accuse is None:
        return
    intention.state = AccPaymentIntent.STATE_SENT
    intention.save(update_fields=["state"])


def _payload(intention: AccPaymentIntent) -> dict[str, Any]:
    """Ce qui part chez l'opérateur, et rien de plus."""
    return {
        "reference": intention.external_reference,
        "amount": str(intention.amount),
        "currency": intention.currency,
        "provider": intention.provider_code,
        "expires_at": intention.expires_at.isoformat() if intention.expires_at else "",
    }


def _state_query_answered(tenant: Tenant, intention: AccPaymentIntent) -> bool:
    """La question d'état posée au tiers a-t-elle reçu sa réponse ?

    **Posée AU HUB, dans les termes de l'appelant.** Une première rédaction
    lisait la liste des échanges et comparait elle-même l'opération à `OP8`
    et l'état à « accepté » — ce qui faisait importer `flows.models` et
    `flows.operations` par `accounting`, et la garde de couplage l'a
    refusé. Elle avait raison : un module métier qui connaît le nom des
    états du hub se casse le jour où la machine à états change, sans que
    rien ne le prévienne.

    **Seules comptent les réponses postérieures à cette intention** : une
    facture peut en porter plusieurs successivement, et la réponse obtenue
    pour la précédente ne dit rien de celle-ci."""
    from apps.flows.services.public import has_settled_reference_lookup

    return has_settled_reference_lookup(
        tenant,
        document_type=intention.document_type,
        document_id=intention.document_id,
        since=intention.created_at,
    )


__all__ = [
    "INTENT_VALIDITY_HOURS",
    "LIVE_STATES",
    "REEMIT_CANNOT_ASK",
    "REEMIT_NOTIFIED",
    "REEMIT_QUERY_SENT",
    "REEMIT_REPLACED",
    "REEMIT_SETTLED",
    "REEMIT_STILL_PAYABLE",
    "REFERENCE_PREFIX",
    "ReemitResult",
    "create_payment_intent",
    "reemit_intent",
]
