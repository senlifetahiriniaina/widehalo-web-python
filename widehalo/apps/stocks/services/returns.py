"""Retours client (STK-RMA1, §5.8, ST6 du sous-sequencement `stocks` — cf.
plan) : cycle de vie `draft -> processed` (ou `-> cancelled` avant
traitement), meme discipline "immuable une fois traite, correction par
mouvement inverse" que `StkMove`/`StkPicking`/`StkInventory`.

Ce module n'implemente AUCUNE logique de mouvement lui-meme —
`process_return` orchestre exclusivement le moteur ST2
(`services.moves.create_move`/`validate_move`), jamais reimplemente ici
(RG-STK-1/RG-STK-2 restent portees integralement par `services.moves`),
meme discipline exacte que `services.pickings`/`services.quality`."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.stocks.models import StkLocation, StkMove, StkReturn
from apps.stocks.services.moves import create_move, validate_move


def create_return(
    *,
    tenant: Tenant,
    partner_id: Any,
    variant_id: Any,
    qty: Decimal,
    date: dt.date,
    reason: str,
    source_document: str = "",
) -> StkReturn:
    """Cree un retour en `draft`, sans `quality_state`/`decision` — ces
    deux champs restent vides jusqu'a `assess_return` (l'evaluation qualite
    du retour est une etape distincte de sa simple constatation, meme
    principe temporel que `StkQualityState`, cf. `services.quality.
    set_quality_state`, cree separement de la decision de relocalisation)."""
    reference = next_reference(tenant, "STKRET", date.year)
    return StkReturn.objects.create(
        tenant=tenant,
        reference=reference,
        partner_id=partner_id,
        source_document=source_document,
        date=date,
        reason=reason,
        variant_id=variant_id,
        qty=qty,
        state=StkReturn.STATE_DRAFT,
    )


def assess_return(return_obj: StkReturn, *, quality_state: str, decision: str) -> StkReturn:
    """Fixe `quality_state`/`decision` sur un retour encore `draft` — ne
    deplace AUCUN stock (une evaluation n'est pas encore un traitement,
    cf. docstring de module). Refuse (`ValidationError` i18n) si le retour
    n'est plus `draft` (une evaluation une fois le retour `processed`/
    `cancelled` n'a plus de sens : le stock a deja bouge, ou le retour est
    abandonne)."""
    if return_obj.state != StkReturn.STATE_DRAFT:
        raise ValidationError(_("Seul un retour en brouillon peut etre evalue."))
    return_obj.quality_state = quality_state
    return_obj.decision = decision
    return_obj.save(update_fields=["quality_state", "decision"])
    return return_obj


@transaction.atomic
def process_return(
    return_obj: StkReturn, *, location_to: StkLocation, user: User | None = None
) -> StkReturn:
    """`draft -> processed` : cree et valide un VRAI `StkMove`
    (`move_type="retour"`, moteur ST2 reutilise integralement) transferant
    `return_obj.qty` de l'emplacement virtuel `client` (resolu ici via
    `StkLocation.TYPE_CLIENT` du meme entrepot que `location_to` — le
    "cote client" symetrique de toute livraison, meme logique double-entree
    que RG-STK-1) vers `location_to`.

    **`location_to` : decision metier laissee A L'APPELANT.** Ce service
    n'encode AUCUN choix d'emplacement selon `quality_state`/`decision` —
    l'appelant (ecran/API) resout lui-meme l'emplacement pertinent (ex. une
    zone de reception interne `TYPE_INTERNE` pour un retour `conforme`/
    `defaut_mineur` destine a `remplacement`, ou un emplacement `TYPE_REBUT`
    pour `decision="refus"`/`quality_state` `defaut_majeur`/`rebut`) —
    exactement le meme design que `services.quality.apply_quality_decision`
    (`quarantine_or_scrap_location` fourni par l'appelant, jamais devine
    ici), pour la meme raison : ce module de bas niveau execute le
    mouvement, il ne porte pas le jugement metier sur OU l'envoyer.

    Refuse (`ValidationError` i18n) si `quality_state`/`decision` ne sont
    pas encore renseignes (l'evaluation via `assess_return` est un
    prealable OBLIGATOIRE), ou si le retour n'est plus `draft`
    (`processed`/`cancelled` : deja traite ou abandonne)."""
    if return_obj.state != StkReturn.STATE_DRAFT:
        raise ValidationError(_("Seul un retour en brouillon peut etre traite."))
    if not return_obj.quality_state or not return_obj.decision:
        raise ValidationError(
            _("Un retour doit etre evalue (etat qualite et decision) avant d'etre traite.")
        )

    client_location = StkLocation.objects.filter(
        tenant=return_obj.tenant,
        warehouse=location_to.warehouse,
        type=StkLocation.TYPE_CLIENT,
    ).first()
    if client_location is None:
        raise ValidationError(
            _(
                "Aucun emplacement virtuel client trouve pour l'entrepot de "
                "destination — impossible de tracer l'origine du retour."
            )
        )

    move = create_move(
        tenant=return_obj.tenant,
        variant_id=return_obj.variant_id,
        qty=return_obj.qty,
        uom="",
        location_from=client_location,
        location_to=location_to,
        date=return_obj.date,
        move_type=StkMove.TYPE_RETOUR,
        source_document=return_obj.source_document or (return_obj.reference or ""),
        operator=user,
    )
    validate_move(move)

    return_obj.move = move
    return_obj.state = StkReturn.STATE_PROCESSED
    return_obj.save(update_fields=["move", "state"])
    return return_obj


def cancel_return(return_obj: StkReturn, *, reason: str) -> StkReturn:
    """`draft -> cancelled` uniquement — un retour `processed` a deja un
    effet de stock reel et immuable (correction par mouvement inverse,
    jamais d'annulation retroactive), meme discipline exacte que
    `services.moves.cancel_move`/`services.pickings.cancel_picking`. Motif
    obligatoire (`ValidationError` i18n si vide, meme convention que
    partout ailleurs dans ce depot)."""
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour annuler un retour."))
    if return_obj.state != StkReturn.STATE_DRAFT:
        raise ValidationError(
            _("Seul un retour en brouillon peut etre annule — un retour traite est immuable.")
        )
    return_obj.state = StkReturn.STATE_CANCELLED
    return_obj.save(update_fields=["state"])
    return return_obj
