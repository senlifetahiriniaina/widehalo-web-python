"""S2 (Phase 4, bloc A) — machine a etats de l'echange.

Neuf etats, et TROIS INVARIANTS que le cahier pose explicitement. Ils sont
ecrits ici comme des donnees inspectables (`_ALLOWED_TRANSITIONS`,
`TERMINAL_STATES`, `INCIDENT_WORTHY_STATES`) plutot que comme des
decorateurs disperses sur le modele : un invariant qu'on ne peut pas LIRE
d'un seul tenant est un invariant que la prochaine transition ajoutee
violera sans que personne ne s'en apercoive. Les deux patrons existent dans
ce depot — `django_fsm` sur `SalesOrder`, transitions en service dans
`accounting.services.moves` — et le plan tranche pour le second.

**Invariant 1 — `ACCEPTE` et `REJETE` sont TERMINAUX.** Le tiers a tranche.
Rien n'en repart : ni une relance, ni un rejeu. Un rejeu supervise cree un
NOUVEL echange (S4), il ne reecrit jamais celui-ci — sans quoi le registre
cesserait d'etre une trace et deviendrait un etat courant, ce qui est
exactement ce que « le registre est au flux ce que le mouvement est au
stock » interdit.

**Invariant 2 — `ATTENTE_VERDICT` n'expire JAMAIS, mais porte une echeance
de RELANCE.** La nuance est le coeur du critere. Faire expirer cet etat vers
`EN_ECHEC` au bout de N jours inventerait un verdict que le tiers n'a pas
rendu : une soumission fiscale « en echec » parce que l'administration est
lente est un faux, et un faux qui declenche des relances commerciales
aupres d'un client dont la facture est en realite valide. L'echeance porte
donc sur la RELANCE (`relance_due_at`), jamais sur l'etat.

**Invariant 3 — `SUSPENDU` n'ouvre PAS d'incident.** Un plafond de cout
atteint est un fonctionnement NORMAL de la gouvernance, decide par le
client lui-meme. L'ouvrir comme incident noierait les vraies pannes sous
des alertes volontaires — c'est la meme distinction que L10 a du faire
entre « refuse parce que le consentement a ete retire » et « tombe sur une
panne reseau ».

**Ce que ce module NE fait pas, et pourquoi.** Aucun appel reseau, aucune
mise en file : la file et le disjoncteur sont S3, l'idempotence S4. Ici on
prepare et on fait avancer un etat. C'est ce qui rend FLX-2 tenable — « un
echec de tiers sur declencheur evenementiel n'empeche pas la transition
metier » : preparer un echange ne peut pas echouer pour une raison qui
appartient au tiers, puisque le tiers n'est pas appele.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.flows.models import FlwExchange, FlwPayload

if TYPE_CHECKING:
    from uuid import UUID

    from apps.core.models.tenant import Tenant
    from apps.flows.models import FlwLink

# --- Les trois invariants, sous forme de donnees ------------------------------

#: Invariant 1. Rien ne part de ces etats : le tiers a tranche.
TERMINAL_STATES = FlwExchange.TERMINAL_STATES

#: Invariant 3. `SUSPENDU` en est volontairement ABSENT — un plafond atteint
#: est une decision du client, pas une panne. S3 lira cet ensemble pour
#: decider s'il ouvre un incident.
INCIDENT_WORTHY_STATES = frozenset({FlwExchange.STATE_FAILED})

#: Le graphe complet. Une transition absente d'ici est refusee : la table
#: est la seule source de verite, jamais une suite de `if` dans un service
#: appelant.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    FlwExchange.STATE_PREPARED: frozenset(
        {
            FlwExchange.STATE_QUEUED,
            # Plafond atteint AVANT la mise en file : on ne consomme pas la
            # file pour un echange qu'on sait bloque.
            FlwExchange.STATE_SUSPENDED,
            # Refus de gouvernance (modele non approuve, consentement
            # retire...) : jamais un reessai, la cause ne passera pas avec
            # le temps. Meme distinction qu'en L10.
            FlwExchange.STATE_FAILED,
        }
    ),
    FlwExchange.STATE_QUEUED: frozenset(
        {
            FlwExchange.STATE_SENT,
            FlwExchange.STATE_TO_RETRY,
            FlwExchange.STATE_FAILED,
            FlwExchange.STATE_SUSPENDED,
        }
    ),
    FlwExchange.STATE_SENT: frozenset(
        {
            FlwExchange.STATE_ACCEPTED,
            FlwExchange.STATE_REJECTED,
            FlwExchange.STATE_AWAITING_VERDICT,
            FlwExchange.STATE_TO_RETRY,
            FlwExchange.STATE_FAILED,
        }
    ),
    FlwExchange.STATE_AWAITING_VERDICT: frozenset(
        {
            FlwExchange.STATE_ACCEPTED,
            FlwExchange.STATE_REJECTED,
            # Relance : on redemande, on n'invente pas de verdict.
            FlwExchange.STATE_TO_RETRY,
            FlwExchange.STATE_FAILED,
        }
    ),
    FlwExchange.STATE_TO_RETRY: frozenset({FlwExchange.STATE_QUEUED, FlwExchange.STATE_FAILED}),
    # `EN_ECHEC` est un PUITS, sans etre « terminal » au sens de
    # l'invariant 1 : le tiers n'a rien tranche, c'est nous qui avons
    # renonce. La difference est visible au rejeu — un echange accepte ne se
    # rejoue pas, un echange en echec se rejoue en creant un SUCCESSEUR
    # (S4), relie par `correlation_key`, jamais en rouvrant celui-ci. Le
    # jour ou une transition partirait d'ici, le registre cesserait d'etre
    # une trace pour devenir un etat courant.
    FlwExchange.STATE_FAILED: frozenset(),
    FlwExchange.STATE_SUSPENDED: frozenset(
        {
            # Le plafond est releve ou le mois change : l'echange repart.
            FlwExchange.STATE_QUEUED,
            FlwExchange.STATE_FAILED,
        }
    ),
    FlwExchange.STATE_ACCEPTED: frozenset(),
    FlwExchange.STATE_REJECTED: frozenset(),
}


def allowed_targets(state: str) -> frozenset[str]:
    """Etats atteignables depuis `state`. Vide pour un etat terminal ou
    pour un puits — la fonction ne leve jamais sur un etat inconnu, elle
    renvoie l'ensemble vide : un etat inconnu ne doit rien autoriser."""
    return _ALLOWED_TRANSITIONS.get(state, frozenset())


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def opens_incident(state: str) -> bool:
    """Invariant 3, sous forme interrogeable par S3.

    `SUSPENDU` repond `False` : un plafond atteint est une decision du
    client, pas une panne. Ouvrir un incident dessus noierait les vraies
    pannes sous des alertes volontaires."""
    return state in INCIDENT_WORTHY_STATES


# --- Preparation --------------------------------------------------------------


def prepare_exchange(
    tenant: Tenant,
    link: FlwLink,
    *,
    operation: str,
    direction: str = FlwExchange.DIRECTION_OUTBOUND,
    body: str = "",
    document_type: str = "",
    document_id: UUID | None = None,
    correlation_key: str = "",
    content_type: str = "application/json",
) -> FlwExchange:
    """Cree un echange en `PREPARE`, avec sa charge utile et son empreinte.

    **Ne touche a RIEN d'externe**, et c'est ce qui rend FLX-2 tenable :
    « un echec de tiers sur declencheur evenementiel n'empeche pas la
    transition metier ». Preparer un echange ne peut pas echouer pour une
    raison qui appartient au tiers, puisqu'aucun tiers n'est appele. Un
    declencheur branche sur une transition metier (S5) peut donc appeler
    cette fonction sans mettre la transition en peril.

    L'empreinte est calculee ICI, a la creation, et jamais recalculee
    ensuite : c'est ce qui doit survivre a la purge de la charge utile
    (FLX-5). La recalculer plus tard, apres purge, ne donnerait rien ; la
    recalculer avant donnerait la meme valeur et n'apporterait rien. Une
    seule ecriture, au seul moment ou le corps est connu."""
    now = timezone.now()
    exchange = FlwExchange.objects.create(
        tenant=tenant,
        link=link,
        direction=direction,
        operation=operation,
        state=FlwExchange.STATE_PREPARED,
        document_type=document_type,
        document_id=document_id,
        correlation_key=correlation_key,
        payload_fingerprint=FlwExchange.fingerprint_of(body) if body else "",
        partition_month=FlwExchange.month_of(now.date()),
    )
    if body:
        FlwPayload.objects.create(
            tenant=tenant,
            exchange=exchange,
            content_type=content_type,
            body=body,
            byte_size=len(body.encode("utf-8")),
        )
    return exchange


# --- Transition ----------------------------------------------------------------


def transition_exchange(
    exchange: FlwExchange,
    *,
    to_state: str,
    result_code: str = "",
    result_message: str = "",
    relance_due_at: Any = None,
) -> FlwExchange:
    """Fait avancer un echange, ou refuse.

    Refuse par `ValidationError` — jamais en ignorant silencieusement la
    demande : une transition refusee sans bruit laisserait l'appelant croire
    que l'echange a avance, et le registre dirait autre chose que le code.

    `relance_due_at` n'a de sens que pour `ATTENTE_VERDICT` (invariant 2).
    Le passer ailleurs est une erreur d'appel, signalee comme telle plutot
    qu'absorbee."""
    if is_terminal(exchange.state):
        raise ValidationError(
            _(
                "Échange %(id)s déjà tranché par le tiers (%(state)s) : "
                "un rejeu crée un nouvel échange, il ne rouvre jamais celui-ci."
            )
            % {"id": exchange.id, "state": exchange.state}
        )
    if to_state not in allowed_targets(exchange.state):
        raise ValidationError(
            _("Transition refusée : %(from)s -> %(to)s.") % {"from": exchange.state, "to": to_state}
        )
    if relance_due_at is not None and to_state != FlwExchange.STATE_AWAITING_VERDICT:
        raise ValidationError(_("Une échéance de relance ne s'applique qu'à l'attente de verdict."))

    now = timezone.now()
    fields = ["state"]
    exchange.state = to_state

    if to_state == FlwExchange.STATE_SENT:
        exchange.sent_at = now
        exchange.attempt += 1
        fields += ["sent_at", "attempt"]
    elif to_state == FlwExchange.STATE_AWAITING_VERDICT:
        # Invariant 2 : une ECHEANCE DE RELANCE, jamais une expiration.
        # `next_attempt_at` porte la date a laquelle on REDEMANDERA ; rien
        # ne fera basculer cet echange en echec au seul motif du temps
        # ecoule.
        exchange.next_attempt_at = relance_due_at
        fields.append("next_attempt_at")
    elif to_state in TERMINAL_STATES:
        exchange.settled_at = now
        fields.append("settled_at")

    if result_code:
        exchange.result_code = result_code
        fields.append("result_code")
    if result_message:
        exchange.result_message = result_message
        fields.append("result_message")

    exchange.save(update_fields=fields)
    return exchange


def exchanges_due_for_relance(tenant: Tenant, *, now: Any = None) -> list[FlwExchange]:
    """Echanges en attente de verdict dont l'echeance de RELANCE est
    passee.

    Ils restent en `ATTENTE_VERDICT` — cette fonction ne les fait pas
    basculer, elle les DESIGNE. C'est l'appelant (S3) qui decidera de
    redemander, et redemander est une action, pas un changement d'etat
    automatique du a l'horloge."""
    moment = now or timezone.now()
    return list(
        FlwExchange.objects.filter(
            tenant=tenant,
            state=FlwExchange.STATE_AWAITING_VERDICT,
            next_attempt_at__isnull=False,
            next_attempt_at__lte=moment,
        ).order_by("next_attempt_at")
    )


__all__ = [
    "INCIDENT_WORTHY_STATES",
    "TERMINAL_STATES",
    "allowed_targets",
    "exchanges_due_for_relance",
    "is_terminal",
    "opens_incident",
    "prepare_exchange",
    "transition_exchange",
]
