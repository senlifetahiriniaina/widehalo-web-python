"""Defauts et etats qualite (§5.8, ST3 du sous-sequencement `stocks` — cf.
plan) : RG-STK-7 — classification qualite d'un quant ou d'un lot, et
consequence physique du passage en `defaut_majeur`/`rebut` (deplacement
vers un emplacement dedie, sans sortir la valeur du perimetre trace).

**Emplacement de quarantaine (`en_quarantaine`)** : `StkLocation.
TYPE_CHOICES` (ST1) n'a pas de type dedie pour la quarantaine — seul
`TYPE_REBUT` existe pour ce cas de figure proche. Choix retenu ici :
reutiliser un emplacement `TYPE_INVENTAIRE` (emplacement virtuel d'ecart,
le plus proche semantiquement d'un "stock mis a part en attente de
decision" parmi les types deja modelises) plutot que de rouvrir ST1 pour y
ajouter un type — les choix `TYPE_CHOICES` deja commits ne sont pas
modifies sans necessite demontree. Note ceci dit assumee comme un
GAP MINEUR de ST1 : un futur `TYPE_QUARANTAINE` dedie serait plus exact
qu'un `TYPE_INVENTAIRE` detourne de son usage premier (ecart d'inventaire,
pas classification qualite), mais RG-STK-7 ne declenche de toute facon
AUCUN `StkMove` pour l'etat `en_quarantaine` lui-meme (cf.
`apply_quality_decision` ci-dessous, seuls `defaut_majeur`/`rebut`
relocalisent physiquement) — ce choix de type d'emplacement n'a donc
aucune consequence sur la valorisation ou la double entree tant que ST3
reste dans son perimetre. L'appelant de `apply_quality_decision` choisit
lui-meme l'emplacement `quarantine_or_scrap_location` (un `TYPE_REBUT`
pour `rebut`, un `TYPE_INVENTAIRE` ou tout autre emplacement interne dedie
pour `defaut_majeur`) — ce module n'impose aucun type precis."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.stocks.models import (
    StkDefectType,
    StkLocation,
    StkLot,
    StkMove,
    StkQualityState,
    StkQuant,
)
from apps.stocks.services.moves import create_move, validate_move

# Seuls ces deux etats declenchent une relocalisation physique (RG-STK-7,
# wording litteral du CDC — "Le passage en `defaut_majeur` ou `rebut`
# sort la quantite du stock disponible..."). `conforme`/`defaut_mineur`/
# `en_quarantaine`/`declasse` n'en declenchent aucune.
_RELOCATION_STATES = (StkQualityState.STATE_DEFAUT_MAJEUR, StkQualityState.STATE_REBUT)


def set_quality_state(
    *,
    tenant: Tenant,
    quant: StkQuant | None = None,
    lot: StkLot | None = None,
    state: str,
    defect_type: StkDefectType | None = None,
    defect_qty: Decimal = Decimal(0),
    description: str = "",
    photos: list[UUID] | None = None,
    decided_by: User | None = None,
) -> StkQualityState:
    """Cree l'enregistrement de classification qualite. Refuse
    (`ValidationError` i18n) si `quant`/`lot` sont tous deux `None` ou
    tous deux renseignes — XOR STRICT, a la difference du traitement plus
    souple de `StkMeasurement.move`/`quant` (cf. docstring `models.py`) :
    une `StkQualityState` EST une decision de classification, elle doit
    toujours porter sans ambiguite sur une seule unite de stock precise.

    `decided_at` est toujours fixe a l'instant de l'appel (creer cet
    enregistrement EST l'acte de decision, meme si `decided_by` n'est pas
    fourni — ex. une regle automatique sans utilisateur humain identifie)."""
    if (quant is None) == (lot is None):
        raise ValidationError(
            _(
                "Renseigner exactement un quant ou un lot pour un état qualité, "
                "jamais les deux ni aucun."
            )
        )
    return StkQualityState.objects.create(
        tenant=tenant,
        quant=quant,
        lot=lot,
        state=state,
        defect_type=defect_type,
        defect_qty=defect_qty,
        description=description,
        photos=[str(photo_id) for photo_id in (photos or [])],
        decided_by=decided_by,
        decided_at=timezone.now(),
    )


def apply_quality_decision(
    quality_state: StkQualityState, *, quarantine_or_scrap_location: StkLocation
) -> StkMove | None:
    """RG-STK-7 : quand `quality_state.state` est `defaut_majeur` ou
    `rebut` ET que `quality_state.quant` est renseigne (un `lot` seul, sans
    quant, ne designe pas un emplacement d'origine — rien a deplacer),
    cree et valide un VRAI `StkMove` (moteur ST2 reutilise integralement,
    aucune logique de mouvement reinventee ici) transferant la quantite
    defectueuse du quant vers `quarantine_or_scrap_location`.

    **Quantite transferee** : `quality_state.defect_qty` si renseignee
    (`> 0`), sinon la quantite COMPLETE du quant — un appelant qui n'a pas
    precise de quantite partielle est presume vouloir dire "tout le
    quant" (une classification qualite sans quantite de defaut explicite
    porte, par defaut, sur l'integralite de l'unite classifiee).

    **"Restant valorisee jusqu'a decision"** : vrai PAR CONSTRUCTION une
    fois l'ajustement `services.moves._is_valuation_internal` applique
    (cf. sa docstring) — ce mouvement est un transfert interne->interne au
    sens valorisation des lors que `quarantine_or_scrap_location.type`
    vaut `TYPE_REBUT` (ou tout autre type deja classe "interne" au sens
    valorisation), donc `validate_move` reprend le cout unitaire du quant
    source et cree/consomme AUCUNE couche — la valeur ne quitte jamais le
    perimetre trace, elle change seulement d'emplacement, exactement
    l'exigence du CDC. Si l'appelant choisit malgre tout un emplacement
    d'un type non couvert par `_is_valuation_internal` (ex. un
    `TYPE_INVENTAIRE` pour la quarantaine, cf. docstring de module
    ci-dessus), `validate_move` traiterait alors ce mouvement comme une
    sortie reelle (consommation FIFO) — a la charge de l'appelant de
    choisir un emplacement de type `TYPE_REBUT`/`TYPE_INTERNE` pour
    preserver "restant valorisee" au sens strict ; ce module ne force pas
    ce choix de type d'emplacement (cf. docstring de module).

    Renvoie `None` (aucun mouvement necessaire) pour tout autre etat, ou
    si `quality_state.quant` est `None`, ou si la quantite a deplacer est
    nulle."""
    if quality_state.state not in _RELOCATION_STATES:
        return None
    quant = quality_state.quant
    if quant is None:
        return None
    qty = quality_state.defect_qty if quality_state.defect_qty > 0 else quant.qty
    if qty <= 0:
        return None
    move = create_move(
        tenant=quality_state.tenant,
        variant_id=quant.variant_id,
        qty=qty,
        uom=quant.uom,
        location_from=quant.location,
        location_to=quarantine_or_scrap_location,
        date=timezone.now().date(),
        move_type=StkMove.TYPE_REBUT,
        lot=quant.lot,
    )
    return validate_move(move)
