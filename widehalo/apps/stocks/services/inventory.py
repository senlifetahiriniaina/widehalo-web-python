"""Inventaire physique (§5.8, ST5 du sous-sequencement `stocks` — cf.
plan) : RG-STK-9 — cycle de vie `draft -> in_progress -> validated`
(`cancelled` depuis `draft`/`in_progress`), comptage ligne par ligne avec
ecart contre `StkQuant`, et generation automatique, a la validation, d'un
VRAI `StkMove` d'ajustement par ligne en ecart (moteur ST2 reutilise
integralement) suivie de l'ecriture comptable de regularisation
(`accounting.services.public.create_stock_movement_entry_from_source`,
gap ajoute par ce meme ST5, renommee et generalisee par A3 — Phase 3
§5.8 — pour couvrir aussi les mouvements ordinaires depuis
`services.moves.validate_move`, cf. sa docstring).

**Emplacement virtuel de contrepartie (`StkLocation.TYPE_INVENTAIRE`)** :
chaque `StkWarehouse` a besoin d'un emplacement virtuel dedie a l'ecart
d'inventaire pour porter la double entree RG-STK-1 des mouvements
d'ajustement — `_resolve_variance_location` le trouve ou le cree
(`services.warehouses.create_location`, ST1 reutilise) au lieu d'exiger
que l'appelant en fournisse un explicitement, pour que
`validate_inventory` reste appelable sans configuration prealable. A la
difference de la quarantaine qualite (ST3, qui detourne ce meme type
faute de mieux, cf. `services/quality.py`), c'est ici l'usage PREMIER de
ce type d'emplacement (RG-STK-1, "ecart d'inventaire") — aucun
detournement.

**Valorisation de l'ajustement** : PAS d'exception a
`services.moves._is_valuation_internal` necessaire ici, a la difference
de RG-STK-7 (rebut) — un emplacement `TYPE_INVENTAIRE` N'EST PAS classe
"interne" au sens valorisation (cf. sa docstring), ce qui est exactement
le comportement souhaite pour un ajustement d'inventaire (a la difference
d'un rebut qui doit "rester valorise") : un ecart POSITIF (comptage >
theorique) doit reellement CREER de la valeur (nouvelle couche FIFO, le
mouvement va du virtuel `TYPE_INVENTAIRE` vers l'emplacement interne
compte — donc `to_internal and not from_internal`) ; un ecart NEGATIF doit
reellement CONSOMMER de la valeur (le mouvement va de l'emplacement
interne vers le virtuel `TYPE_INVENTAIRE` — donc `from_internal and not
to_internal`, consommation FIFO). C'est exactement la semantique
comptable d'un ajustement d'inventaire reel."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.accounting.services.public import create_stock_movement_entry_from_source
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.audit import log_action
from apps.core.services.sequences import next_reference
from apps.stocks.models import (
    StkInventory,
    StkInventoryLine,
    StkLocation,
    StkLot,
    StkMove,
    StkWarehouse,
)
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.quants import get_quant
from apps.stocks.services.warehouses import create_location

# RG-STK-9 : "l'ecart superieur au seuil exige un motif ET une validation
# hierarchique". Le CDC ne fixe pas de valeur par defaut pour ce seuil
# (contrairement a RG-STK-4, "seuil parametrable, defaut 3%", qui porte
# sur un ecart de MESURE physique a la reception, une notion distincte).
# 5% retenu ici comme defaut assume — volontairement plus large que le 3%
# de RG-STK-4 : un ecart de comptage d'inventaire (erreur humaine de
# denombrement, casse non tracee, vol...) est structurellement plus
# tolerant en pratique qu'un ecart de mesure a reception (controle
# qualite d'un lot recu, ou 3% est deja considere significatif) — une
# tolerance de cycle-count usuelle en gestion d'entrepot se situe
# generalement dans la fourchette 2-5%, 5% retenu ici comme borne haute
# assumee plutot que de reprendre telle quelle la valeur RG-STK-4 sans
# justification propre au contexte "inventaire".
DEFAULT_VARIANCE_THRESHOLD_PCT = Decimal("5")

# Code/nom de l'emplacement virtuel d'ecart d'inventaire cree/reutilise
# par entrepot (cf. docstring de module ci-dessus).
_VARIANCE_LOCATION_CODE = "INV-ECART"


def _ratio_or_none(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Meme garde que `services.moves._ratio_or_none`/
    `services.measurements._variance_pct_or_none` — reimplementee ici
    plutot qu'importee (fonction privee triviale, meme discipline
    "reimplementer plutot que traverser un import prive inter-fichiers")."""
    if denominator == 0:
        return None
    return numerator / denominator


def _resolve_variance_location(warehouse: StkWarehouse) -> StkLocation:
    """Trouve ou cree l'emplacement virtuel `TYPE_INVENTAIRE` dedie de cet
    entrepot — un seul par entrepot (recherche par `warehouse`+`type`
    avant creation, jamais de doublon)."""
    location = StkLocation.objects.filter(
        warehouse=warehouse, type=StkLocation.TYPE_INVENTAIRE
    ).first()
    if location is not None:
        return location
    return create_location(
        tenant=warehouse.tenant,
        warehouse=warehouse,
        code=_VARIANCE_LOCATION_CODE,
        name=_("Écart d'inventaire"),
        type=StkLocation.TYPE_INVENTAIRE,
    )


def create_inventory(
    *,
    tenant: Tenant,
    warehouse: StkWarehouse,
    date: dt.date,
    type: str,  # noqa: A002
    is_blind: bool = False,
) -> StkInventory:
    """`is_blind` ne se pose qu'ici (STK-6, L13) : un mode aveugle qu'on
    peut lever en cours de comptage n'en est pas un. Aucun service, aucune
    vue et aucun endpoint ne le modifie ensuite."""
    reference = next_reference(tenant, "STKINV", date.year)
    return StkInventory.objects.create(
        tenant=tenant,
        reference=reference,
        warehouse=warehouse,
        date=date,
        type=type,
        state=StkInventory.STATE_DRAFT,
        is_blind=is_blind,
    )


def visible_inventory_line_rows(inventory: StkInventory) -> list[dict[str, Any]]:
    """Lignes d'un inventaire, prêtes à être affichées ou sérialisées, avec
    la quantité attendue MASQUÉE tant que la session est aveugle et ouverte.

    **Le seul endroit** où cette décision est prise. Avant L13, le gabarit
    masquait déjà (`{% if inventory.state == "validated" %}`) pendant que
    l'API renvoyait `qty_theoretical` en clair depuis
    `add_inventory_line_endpoint` : deux implémentations d'une même règle,
    dont une seule était juste. Les appelants passent désormais par ici.

    `qty_theoretical` et `difference` valent `None` quand elles sont
    masquées — jamais `0`, qui serait indistinguable d'un stock théorique
    réellement nul (un premier comptage d'emplacement jamais mouvementé, cas
    parfaitement valide)."""
    hidden = inventory.hides_expected_quantity
    rows: list[dict[str, Any]] = []
    for line in inventory.lines.select_related("location", "lot").all():
        rows.append(
            {
                "id": str(line.id),
                "variant_id": str(line.variant_id),
                "location_id": str(line.location_id),
                "location_code": line.location.code,
                "lot_id": str(line.lot_id) if line.lot_id else None,
                "qty_theoretical": None if hidden else line.qty_theoretical,
                "qty_counted": line.qty_counted,
                "difference": None if hidden else line.difference,
                "reason": line.reason,
            }
        )
    return rows


def add_inventory_line(
    inventory: StkInventory,
    *,
    variant_id: Any,
    location: StkLocation,
    lot: StkLot | None = None,
) -> StkInventoryLine:
    """Ajoute une ligne de comptage, `qty_theoretical` PHOTOGRAPHIEE depuis
    le `StkQuant` courant `(variant_id, location, lot)` a l'instant de
    l'appel (0 si aucun quant n'existe encore pour cette combinaison —
    stock theorique nul, un cas parfaitement valide, ex. premier comptage
    d'un emplacement jamais mouvemente). Refuse (`ValidationError` i18n)
    si `inventory.state != "draft"` — le contenu d'un inventaire se fige
    des qu'il quitte le brouillon (meme discipline "gate d'assemblage" que
    `services.pickings.add_picking_line`, restreint ici a `draft` seul,
    plus strict que le picking qui accepte aussi `waiting`)."""
    if inventory.state != StkInventory.STATE_DRAFT:
        raise ValidationError(
            _("Seul un inventaire en brouillon peut recevoir de nouvelles lignes.")
        )
    quant = get_quant(variant_id, location, lot)
    qty_theoretical = quant.qty if quant is not None else Decimal(0)
    return StkInventoryLine.objects.create(
        tenant=inventory.tenant,
        inventory=inventory,
        variant_id=variant_id,
        lot=lot,
        location=location,
        qty_theoretical=qty_theoretical,
    )


def start_inventory(inventory: StkInventory) -> StkInventory:
    """`draft -> in_progress`. Refuse si l'inventaire n'a aucune ligne —
    meme discipline exacte que `services.pickings.mark_picking_ready`
    ("un picking sans ligne ne peut pas etre marque pret")."""
    if inventory.state != StkInventory.STATE_DRAFT:
        raise ValidationError(_("Seul un inventaire en brouillon peut être démarré."))
    if not inventory.lines.exists():
        raise ValidationError(_("Un inventaire sans ligne ne peut pas être démarré."))
    inventory.state = StkInventory.STATE_IN_PROGRESS
    inventory.save(update_fields=["state"])
    return inventory


def record_count(
    line: StkInventoryLine,
    *,
    qty_counted: Decimal,
    counted_by: User | None = None,
    reason: str = "",
    threshold_pct: Decimal = DEFAULT_VARIANCE_THRESHOLD_PCT,
) -> StkInventoryLine:
    """Enregistre le comptage physique d'une ligne — `difference` calculee
    et persistee ici (`qty_counted - qty_theoretical`).

    RG-STK-9 : "l'ecart superieur au seuil exige un motif". Refuse
    (`ValidationError` i18n) si l'ecart RELATIF (`|difference| /
    qty_theoretical * 100`) depasse `threshold_pct` ET qu'aucun `reason`
    n'est fourni. Garde de denominateur nul (`qty_theoretical == 0`) :
    meme traitement "100%/bloquant" que
    `purchase.services.invoicing.three_way_match` — un `qty_theoretical`
    nul avec un `qty_counted` non nul est TOUJOURS un ecart maximal par
    construction (compter quelque chose la ou rien n'etait attendu ne
    peut structurellement pas rester sous un seuil en pourcentage), jamais
    une division par zero silencieusement ignoree ; `qty_theoretical == 0`
    ET `qty_counted == 0` reste un ecart de 0% (rien compte sur rien
    attendu, coherent, aucun motif exige).

    **La validation hierarchique elle-meme (au-dela du motif) est du
    ressort de `validate_inventory`, jamais de cette fonction** — cf.
    docstring de module et de `validate_inventory` : le motif est exige
    ICI, au moment du comptage, la validation hierarchique intervient
    PLUS TARD, au moment de valider le document complet."""
    difference = qty_counted - line.qty_theoretical
    ratio = _ratio_or_none(abs(difference), line.qty_theoretical)
    variance_pct = (
        ratio * 100 if ratio is not None else (Decimal(100) if difference != 0 else Decimal(0))
    )
    if variance_pct > threshold_pct and not reason:
        raise ValidationError(
            _(
                "Écart de %(pct)s%% (seuil %(threshold)s%%) : un motif est "
                "obligatoire pour valider ce comptage."
            )
            % {"pct": variance_pct, "threshold": threshold_pct}
        )
    line.qty_counted = qty_counted
    line.difference = difference
    line.counted_by = counted_by
    line.reason = reason
    line.save(update_fields=["qty_counted", "difference", "counted_by", "reason"])
    return line


def validate_inventory(inventory: StkInventory, *, validated_by: User) -> StkInventory:
    """`in_progress -> validated`. Refuse (`ValidationError` i18n) si
    l'inventaire n'est pas `in_progress`, ou si une ligne quelconque n'a
    pas encore ete comptee (`qty_counted is None`) — toutes les lignes
    doivent etre comptees avant validation du document dans son ensemble
    (c'est ICI, a l'echelle du DOCUMENT, que la "validation hierarchique"
    RG-STK-9 se materialise : `validated_by` en porte la trace).

    Pour CHAQUE ligne en ecart (`difference != 0`) : cree et valide un
    VRAI `StkMove` (`move_type=TYPE_AJUSTEMENT`, moteur ST2 reutilise
    integralement via `services.moves.create_move`/`validate_move`, jamais
    de mise a jour de quant reinventee ici) entre `line.location` et
    l'emplacement virtuel d'ecart de l'entrepot (cf.
    `_resolve_variance_location`), puis appelle le gap comptable
    `create_stock_movement_entry_from_source` pour la valeur EXACTE
    calculee par le moteur de mouvement (`move.value_mga`, JAMAIS
    recalculee independamment — meme discipline "aucune tolerance d'ecart
    entre stock et comptabilite" que RG-STK-2).

    **Sens du mouvement** : ecart POSITIF (compte > theorique, le stock
    physique reel est superieur a ce que le systeme croyait) : le
    mouvement part du virtuel `TYPE_INVENTAIRE` vers `line.location`
    (entree). Ecart NEGATIF : le mouvement part de `line.location` vers le
    virtuel (sortie). Le cout unitaire de reference (pour l'entree, faute
    de cout mesure independamment lors d'un comptage physique) est celui
    du quant EXISTANT a `line.location` avant l'ajustement — 0 si aucun
    quant n'existe encore.

    **Ecriture comptable** : ne bloque JAMAIS la validation de
    l'inventaire si la configuration comptable (journal/periode/compte)
    est absente — `create_stock_movement_entry_from_source` retourne
    silencieusement `None` dans ce cas (meme discipline "gap de
    configuration a la charge de l'administrateur du tenant" que les
    autres gaps `accounting.services.public`) ; le mouvement de STOCK,
    lui, est toujours cree et valide independamment du succes de cette
    ecriture — RG-STK-9 porte sur la generation AUTOMATIQUE de l'ecriture
    QUAND la comptabilite est configuree, pas sur une dependance dure du
    stock envers la comptabilite.

    **STK-7 (Phase 3 §6.3, sprint A4) : separation des taches.** Refuse
    (`ValidationError`, tentative JOURNALISEE via `core.services.audit.
    log_action`) si une ligne en ecart a ete comptee ET serait validee par
    la MEME personne (`line.counted_by_id == validated_by.id`), MAIS
    uniquement quand l'ecart RELATIF depasse `DEFAULT_VARIANCE_THRESHOLD_PCT`
    — meme seuil et meme formule que `record_count` ci-dessus (le CDC parle
    d'un « seuil de la famille d'articles », non modelise dans ce depot ;
    le seuil global existant est reutilise comme approximation assumee).
    En dessous du seuil, la meme personne PEUT valider son propre comptage
    — « validation automatique et tracee » (cahier §6.3), pas une omission.
    Cette verification s'execute AVANT toute creation de `StkMove`/
    ecriture comptable (fail-fast, aucun effet de bord partiel en cas de
    refus).

    **Bug reel corrige (revele par le premier passage CI avec une vraie
    base Postgres, pas par la relecture)** : cette fonction n'est PLUS
    decoree `@transaction.atomic` sur toute sa longueur — seule la section
    de mutation ci-dessous (creation des `StkMove`/ecritures) l'est
    explicitement, via un bloc `with transaction.atomic():`. Avant ce
    correctif, le `log_action(...)` de la garde ci-dessus s'executait a
    l'interieur de la MEME transaction que tout le reste de la fonction —
    le `ValidationError` leve juste apres provoquait un ROLLBACK complet
    qui annulait aussi l'ecriture du `AuditLog`, rendant « refusee et
    journalisee » faux en pratique (l'audit ne survivait jamais au refus
    qu'il est censé documenter). Meme piege, meme solution documentee que
    `apps.pos.services.orders.sync_order` (cf. sa docstring) : ne jamais
    envelopper un `log_action`/`AuditLog.objects.create()` de branche
    d'echec dans la transaction qui va etre annulee par l'exception qui
    suit immediatement."""
    if inventory.state != StkInventory.STATE_IN_PROGRESS:
        raise ValidationError(_("Seul un inventaire en cours peut être valide."))
    lines = list(inventory.lines.all())
    if any(line.qty_counted is None for line in lines):
        raise ValidationError(
            _("Toutes les lignes doivent être comptées avant de valider l'inventaire.")
        )

    for line in lines:
        if line.difference == 0 or line.counted_by_id != validated_by.id:
            continue
        ratio = _ratio_or_none(abs(line.difference), line.qty_theoretical)
        variance_pct = (
            ratio * 100
            if ratio is not None
            else (Decimal(100) if line.difference != 0 else Decimal(0))
        )
        if variance_pct > DEFAULT_VARIANCE_THRESHOLD_PCT:
            log_action(
                "stocks.inventory.self_validate",
                actor=validated_by,
                obj=line,
                metadata={
                    "inventory_reference": inventory.reference,
                    "variance_pct": str(variance_pct),
                },
            )
            raise ValidationError(
                _(
                    "Écart de %(pct)s%% sur la ligne %(variant)s : ne peut pas être "
                    "validé par la personne qui a compté (séparation des tâches)."
                )
                % {"pct": variance_pct, "variant": line.variant_id}
            )

    with transaction.atomic():
        variance_location = _resolve_variance_location(inventory.warehouse)

        for line in lines:
            if line.difference == 0:
                continue
            quant = get_quant(line.variant_id, line.location, line.lot)
            unit_cost_mga = quant.unit_cost_mga if quant is not None else Decimal(0)
            if line.difference > 0:
                move = create_move(
                    tenant=inventory.tenant,
                    variant_id=line.variant_id,
                    qty=line.difference,
                    uom="",
                    location_from=variance_location,
                    location_to=line.location,
                    date=inventory.date,
                    move_type=StkMove.TYPE_AJUSTEMENT,
                    source_document=inventory.reference,
                    unit_cost_mga=unit_cost_mga,
                    lot=line.lot,
                )
            else:
                move = create_move(
                    tenant=inventory.tenant,
                    variant_id=line.variant_id,
                    qty=-line.difference,
                    uom="",
                    location_from=line.location,
                    location_to=variance_location,
                    date=inventory.date,
                    move_type=StkMove.TYPE_AJUSTEMENT,
                    source_document=inventory.reference,
                    unit_cost_mga=unit_cost_mga,
                    lot=line.lot,
                )
            move = validate_move(move)

            value = move.value_mga
            if line.difference > 0:
                adjustment_lines = [
                    {
                        "account_id": None,
                        "amount": value,
                        "label": _("Entrée ajustement inventaire"),
                    },
                    {"account_id": None, "amount": -value, "label": _("Écart d'inventaire")},
                ]
            else:
                adjustment_lines = [
                    {
                        "account_id": None,
                        "amount": -value,
                        "label": _("Sortie ajustement inventaire"),
                    },
                    {"account_id": None, "amount": value, "label": _("Écart d'inventaire")},
                ]
            create_stock_movement_entry_from_source(
                tenant=inventory.tenant,
                date=inventory.date,
                lines=adjustment_lines,
                label=inventory.reference,
            )

        inventory.validated_by = validated_by
        inventory.state = StkInventory.STATE_VALIDATED
        inventory.save(update_fields=["validated_by", "state"])
    return inventory


def cancel_inventory(inventory: StkInventory, *, reason: str) -> StkInventory:
    """`draft/in_progress -> cancelled`. Motif obligatoire (`ValidationError`
    i18n si vide). Refuse si `validated` — immuable une fois valide (les
    mouvements/l'ecriture comptable generes sont deja des faits accomplis,
    correction uniquement par un nouvel inventaire/des mouvements
    inverses, jamais par annulation retroactive — meme discipline exacte
    que `services.moves.cancel_move`/`services.pickings.cancel_picking`)."""
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour annuler un inventaire."))
    if inventory.state not in (StkInventory.STATE_DRAFT, StkInventory.STATE_IN_PROGRESS):
        raise ValidationError(_("Un inventaire valide est immuable — il ne peut pas être annule."))
    inventory.state = StkInventory.STATE_CANCELLED
    inventory.save(update_fields=["state"])
    return inventory
