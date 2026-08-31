"""Cycle de vie d'un `StkPicking` (§5.8, ST4 du sous-sequencement `stocks`
— cf. plan) : operation de stock groupee (reception/expedition/transfert
interne), workflow lineaire `draft/waiting -> ready -> done`, avec
`cancelled` atteignable depuis les trois premiers etats (pas de FSM, cf.
docstring `models.StkPicking`).

Ce module n'implemente AUCUNE logique de mouvement lui-meme — il
orchestre exclusivement le moteur ST2 (`services.moves.create_move`/
`validate_move`/`cancel_move`), jamais reimplemente ici (RG-STK-1/
RG-STK-2 restent portees integralement par `services.moves`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.stocks.models import StkLocation, StkLot, StkMove, StkPicking
from apps.stocks.services.moves import cancel_move, create_move, validate_move

# Mapping par defaut `StkPicking.type` -> `StkMove.move_type`, applique par
# `add_picking_line` quand l'appelant ne fournit pas `move_type`
# explicitement :
#
#   StkPicking.type           StkMove.move_type
#   ------------------------  -----------------------------
#   "entree"  (reception)     TYPE_RECEPTION  ("reception")
#   "sortie"  (expedition)    TYPE_LIVRAISON  ("livraison")
#   "interne" (transfert)     TYPE_TRANSFERT_INTERNE ("transfert_interne")
#
# Ce mapping est une commodite par defaut, pas une contrainte : l'appelant
# reste libre de passer un `move_type` explicite pour un cas particulier
# qui ne correspond pas au type "generique" du picking (ex. un picking
# `sortie` qui est en realite un `rebut` ou un `retour` — cf. docstring
# `add_picking_line`).
_DEFAULT_MOVE_TYPE_BY_PICKING_TYPE = {
    StkPicking.TYPE_ENTREE: StkMove.TYPE_RECEPTION,
    StkPicking.TYPE_SORTIE: StkMove.TYPE_LIVRAISON,
    StkPicking.TYPE_INTERNE: StkMove.TYPE_TRANSFERT_INTERNE,
}

# Etats depuis lesquels un picking accepte encore de nouvelles lignes
# (assemblage en cours) — mirroir de `PurRequisition.STATE_DRAFT` seul
# pour `add_requisition_line`, sauf qu'ici `waiting` est traite de la meme
# facon que `draft` (cf. docstring `models.StkPicking`, "waiting" est un
# simple sous-etat de "pas encore pret").
_LINE_ACCEPTING_STATES = (StkPicking.STATE_DRAFT, StkPicking.STATE_WAITING)

# Etats depuis lesquels un picking peut passer `ready` ou etre annule —
# meme logique "draft/waiting" ci-dessus, plus `ready` lui-meme pour
# l'annulation (cf. `cancel_picking`).
_READY_ELIGIBLE_STATES = _LINE_ACCEPTING_STATES
_CANCEL_ELIGIBLE_STATES = (*_LINE_ACCEPTING_STATES, StkPicking.STATE_READY)


def create_picking(
    *,
    tenant: Tenant,
    type: str,
    location_from: StkLocation,
    location_to: StkLocation,
    partner_id: UUID | None = None,
    date_scheduled: dt.date | None = None,
    source_document: str = "",
    carrier: str = "",
    tracking: str = "",
) -> StkPicking:
    """Cree un picking en `draft`. Ne verifie pas `location_from !=
    location_to` ici (a la difference de `services.moves.create_move`) :
    cette garde vit deja au niveau de chaque `StkMove` genere par
    `add_picking_line`, `StkPicking.location_from`/`location_to` ne sont
    que les emplacements PAR DEFAUT proposes a chaque ligne (l'appelant de
    `add_picking_line` peut toujours passer des emplacements differents
    via la creation manuelle d'un `StkMove` distinct s'il le fallait —
    hors perimetre de ce service simple)."""
    reference = next_reference(tenant, "STKPCK", (date_scheduled or timezone.now().date()).year)
    return StkPicking.objects.create(
        tenant=tenant,
        reference=reference,
        type=type,
        partner_id=partner_id,
        location_from=location_from,
        location_to=location_to,
        date_scheduled=date_scheduled,
        state=StkPicking.STATE_DRAFT,
        source_document=source_document,
        carrier=carrier,
        tracking=tracking,
    )


def add_picking_line(
    picking: StkPicking,
    *,
    variant_id: Any,
    qty: Decimal,
    uom: str,
    unit_cost_mga: Decimal = Decimal(0),
    lot: StkLot | None = None,
    move_type: str | None = None,
    operator: User | None = None,
) -> StkMove:
    """Cree un `StkMove` en `draft` rattache a `picking` (`picking=picking`),
    en reutilisant integralement `services.moves.create_move` (jamais de
    logique de creation de mouvement dupliquee ici) — utilise
    `picking.location_from`/`location_to` comme origine/destination du
    mouvement.

    Refuse (`ValidationError` i18n) si `picking.state` n'est ni `draft` ni
    `waiting` — un picking accepte encore de nouvelles lignes tant qu'il
    est en cours d'assemblage, plus une fois `ready` (le contenu est
    fige au passage du gate de `mark_picking_ready`)/`done`/`cancelled`
    (meme discipline "refuse hors etat d'assemblage" que
    `services.requisitions.add_requisition_line`, etendue ici a
    `draft`+`waiting` plutot qu'a `draft` seul, cf. docstring
    `models.StkPicking`).

    `move_type` : resolu depuis `picking.type` via
    `_DEFAULT_MOVE_TYPE_BY_PICKING_TYPE` (cf. table en tete de module)
    quand l'appelant ne le fournit pas explicitement — l'appelant reste
    libre de passer un `move_type` different pour un cas particulier (ex.
    un picking `sortie` qui est en realite un `rebut`/`retour` plutot
    qu'une livraison classique)."""
    if picking.state not in _LINE_ACCEPTING_STATES:
        raise ValidationError(
            _("Seul un picking en brouillon ou en attente peut recevoir de nouvelles lignes.")
        )
    resolved_move_type = move_type or _DEFAULT_MOVE_TYPE_BY_PICKING_TYPE[picking.type]
    move = create_move(
        tenant=picking.tenant,
        variant_id=variant_id,
        qty=qty,
        uom=uom,
        location_from=picking.location_from,
        location_to=picking.location_to,
        date=picking.date_scheduled or timezone.now().date(),
        move_type=resolved_move_type,
        source_document=picking.source_document,
        unit_cost_mga=unit_cost_mga,
        lot=lot,
        operator=operator,
    )
    move.picking = picking
    move.save(update_fields=["picking"])
    return move


def mark_picking_ready(picking: StkPicking) -> StkPicking:
    """`draft/waiting -> ready`. Refuse si le picking n'a aucune ligne —
    meme discipline exacte que `services.requisitions.submit_requisition`
    ("une demande d'achat sans ligne ne peut pas etre soumise")."""
    if picking.state not in _READY_ELIGIBLE_STATES:
        raise ValidationError(
            _("Seul un picking en brouillon ou en attente peut être marque prêt.")
        )
    if not picking.moves.exists():
        raise ValidationError(_("Un picking sans ligne ne peut pas être marque prêt."))
    picking.state = StkPicking.STATE_READY
    picking.save(update_fields=["state"])
    return picking


@transaction.atomic
def validate_picking(picking: StkPicking, *, date_done: dt.date | None = None) -> StkPicking:
    """`ready -> done` : valide (via `services.moves.validate_move`, moteur
    ST2 reutilise integralement) CHAQUE `StkMove` `draft` rattache a ce
    picking, puis fixe `date_done` (aujourd'hui par defaut).

    Refuse si le picking n'est pas `ready` — le passage par le gate
    `mark_picking_ready` est un prealable OBLIGATOIRE a la validation,
    jamais un raccourci direct `draft -> done`. Ce gate deliberement
    distinct (plutot qu'une validation qui ferait les deux a la fois) sert
    deux fins : (1) il mirrore l'implication du CDC sur le cycle de vie de
    `stk_picking` (§5.8) qui distingue explicitement l'etat "pret" de
    l'etat "termine", et (2) il offre une etape deliberee de "confirmation
    d'intention" avant un effet irreversible sur le stock — coherent avec
    la facon dont `PurOrder`/`StkMove` eux-memes traitent `done` comme un
    etat immuable (correction uniquement par document inverse, jamais de
    retour arriere) : mieux vaut un gate explicite en amont qu'une
    validation accidentelle.

    `@transaction.atomic` (meme discipline que `StkMove.validate_move` lui-
    meme) : si un des `StkMove` du picking echoue a se valider en cours de
    boucle (ne devrait normalement jamais arriver, les lignes etant deja
    `draft`-valides des leur creation par `add_picking_line`, mais garde
    defensive), AUCUNE des lignes deja traitees dans cet appel n'est
    persistee — tout ou rien."""
    if picking.state != StkPicking.STATE_READY:
        raise ValidationError(_("Seul un picking prêt peut être valide."))
    for move in picking.moves.filter(state=StkMove.STATE_DRAFT):
        validate_move(move)
    picking.state = StkPicking.STATE_DONE
    picking.date_done = date_done or timezone.now().date()
    picking.save(update_fields=["state", "date_done"])
    return picking


def cancel_picking(picking: StkPicking, *, reason: str) -> StkPicking:
    """`draft/waiting/ready -> cancelled`. Refuse si `done` — immuable une
    fois termine, correction par un nouveau picking/mouvements inverses,
    jamais par annulation d'un picking deja effectue (meme discipline
    exacte que `services.moves.cancel_move`). Motif obligatoire
    (`ValidationError` i18n si vide, meme convention que partout ailleurs
    dans ce depot).

    Annule egalement (via `services.moves.cancel_move`, moteur ST2
    reutilise) chaque `StkMove` `draft` encore rattache au picking — un
    picking annule ne doit laisser subsister aucune ligne en attente de
    validation."""
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour annuler un picking."))
    if picking.state not in _CANCEL_ELIGIBLE_STATES:
        raise ValidationError(_("Un picking termine est immuable — il ne peut pas être annule."))
    for move in picking.moves.filter(state=StkMove.STATE_DRAFT):
        cancel_move(move, reason=reason)
    picking.state = StkPicking.STATE_CANCELLED
    picking.save(update_fields=["state"])
    return picking
