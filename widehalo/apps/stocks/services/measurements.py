"""Mesures physiques (§5.8, ST3 du sous-sequencement `stocks` — cf. plan) :
RG-STK-4 (mesures, ecart contre theorique, litige fournisseur automatique)
et RG-STK-5 (conversion m/kg textile, delegation pure a `catalog`).

**"Quantite en stock retenue = la quantite MESUREE, jamais la
theorique" (RG-STK-4, acceptance test §5.8.7 n°3)** : `StkMeasurement`
elle-meme ne peut pas structurellement FORBID un appelant de
`services.moves.create_move` de passer une quantite theorique plutot que
mesuree — c'est une discipline d'appel, pas une garde de code (`stocks`
n'a aucun moyen de savoir, au moment d'un `create_move` quelconque, si le
`qty` fourni provient "vraiment" d'une mesure ou d'un chiffre theorique
invente par l'appelant). Ce module rend neanmoins le comportement CORRECT
le chemin de moindre resistance via `create_reception_move_from_measurement`
ci-dessous : un appelant qui construit une reception a partir d'un rouleau
mesure n'a qu'a passer la `StkMeasurement` elle-meme, `qty` etant alors
TOUJOURS derive de `measurement.value` — jamais transmis independamment,
donc jamais substituable par une valeur theorique par erreur d'appel."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.services.public import convert_textile_measurement
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.purchase.services.public import open_purchase_incident
from apps.stocks.models import StkLocation, StkLot, StkMeasurement, StkMove, StkQuant
from apps.stocks.services.moves import create_move

# RG-STK-4 : "seuil parametrable, defaut 3%".
DEFAULT_VARIANCE_THRESHOLD_PCT = Decimal("3")

# Type de `PurCri` ouvert automatiquement en cas d'ecart de mesure au-dela
# du seuil. Valeur LITTERALE (jamais un import de `apps.purchase.models`,
# interdit par la regle de couplage n°1 — seul `purchase.services.public`
# est autorise) correspondant a `PurCri.TYPE_NON_CONFORMITE`
# ("non_conformite"). Choix justifie contre `PurCri.TYPE_RUPTURE` : un
# ecart de mesure sur une reception (rouleau annonce a 50m, mesure a 47.5m)
# est une non-conformite qualitative/quantitative du LIVRABLE recu — pas
# une rupture de stock (qui designerait plutot l'incapacite du fournisseur
# a livrer DU TOUT), semantique clairement plus proche de
# "non_conformite" parmi les `PurCri.TYPE_CHOICES`.
_DISPUTE_INCIDENT_TYPE = "non_conformite"


def _variance_pct_or_none(value: Decimal, theoretical_value: Decimal) -> Decimal | None:
    """Meme garde que `services.moves._ratio_or_none` (denominateur nul ->
    `None`, jamais `ZeroDivisionError`) — reimplementee ici plutot
    qu'importee, fonction privee triviale, meme discipline "reimplementer
    plutot que traverser un import prive inter-fichiers" que
    `services.moves`/`accounting.services.landed_costs`."""
    if theoretical_value == 0:
        return None
    return abs(value - theoretical_value) / theoretical_value * 100


def record_measurement(
    *,
    tenant: Tenant,
    type: str,  # noqa: A002 — coherent avec `StkMeasurement.type` (nom de champ CDC)
    value: Decimal,
    uom: str,
    theoretical_value: Decimal | None = None,
    move: StkMove | None = None,
    quant: StkQuant | None = None,
    device: str = "",
    measured_by: User | None = None,
    measured_at: dt.datetime | None = None,
    photo_document_id: UUID | None = None,
    threshold_pct: Decimal = DEFAULT_VARIANCE_THRESHOLD_PCT,
    partner_id_for_dispute: Any | None = None,
) -> StkMeasurement:
    """Enregistre une mesure physique. Calcule `variance_pct` contre
    `theoretical_value` quand elle est fournie (sinon `variance_pct` reste
    `None` — toute mesure n'a pas necessairement de theorique de
    reference, ex. un simple controle d'inventaire).

    **Litige fournisseur automatique (RG-STK-4)** : si `variance_pct`
    depasse `threshold_pct`, un incident est ouvert via
    `purchase.services.public.open_purchase_incident` — mais UNIQUEMENT si
    l'appelant fournit `partner_id_for_dispute`. Une mesure n'est pas
    toujours rattachee a un contexte fournisseur identifiable (ex. un
    recomptage d'inventaire interne n'a aucun "fournisseur" a mettre en
    litige) : c'est a l'appelant de fournir ce `partner_id` uniquement
    quand le contexte de la mesure EST une reception fournisseur — jamais
    a cette fonction de fabriquer ou deviner un fournisseur.

    Ne peut PAS echouer sur l'ouverture de l'incident : `open_purchase_incident`
    est une enveloppe fine sans dependance de configuration tenant (a la
    difference des gaps `accounting` qui dependent d'une config fiscale
    potentiellement absente) — elle cree systematiquement un `PurCri`
    valide des lors que ses parametres obligatoires sont fournis, ce qui
    est garanti ici (`tenant`/`type`/`partner_id`/`description` sont
    toujours renseignes dans cette branche). Aucun `try/except` de
    protection n'est donc ajoute ici : ce serait de la defense contre une
    defaillance qui ne peut structurellement pas se produire a cet appel."""
    variance_pct = (
        _variance_pct_or_none(value, theoretical_value) if theoretical_value is not None else None
    )

    measurement = StkMeasurement.objects.create(
        tenant=tenant,
        move=move,
        quant=quant,
        type=type,
        value=value,
        uom=uom,
        device=device,
        measured_by=measured_by,
        measured_at=measured_at or timezone.now(),
        variance_pct=variance_pct,
        photo_document_id=photo_document_id,
    )

    exceeds_threshold = variance_pct is not None and variance_pct > threshold_pct
    dispute_needed = exceeds_threshold and partner_id_for_dispute is not None
    if dispute_needed:
        open_purchase_incident(
            tenant=tenant,
            type=_DISPUTE_INCIDENT_TYPE,
            partner_id=partner_id_for_dispute,
            description=_(
                "Ecart de mesure de %(pct)s%% (seuil %(threshold)s%%) — "
                "mesure %(type)s : %(value)s %(uom)s (theorique : %(theoretical)s %(uom)s)."
            )
            % {
                "pct": variance_pct,
                "threshold": threshold_pct,
                "type": type,
                "value": value,
                "theoretical": theoretical_value,
                "uom": uom,
            },
        )

    return measurement


def convert_measurement(
    variant_id: Any, *, length_m: Decimal | None = None, weight_kg: Decimal | None = None
) -> dict[str, Decimal] | None:
    """RG-STK-5 : delegation PURE a `catalog.services.public.
    convert_textile_measurement` — aucun calcul de conversion duplique
    ici. `stocks` n'a d'ailleurs aucun moyen de le faire lui-meme sans
    violer la regle de couplage n°1 (le grammage/laize vit sur
    `catalog.TextileSpec`, jamais accessible directement).

    L'exigence RG-STK-5 "les deux unites sont affichees simultanement sur
    les ecrans de stock" est un besoin de PRESENTATION (ecrans, ST7 du
    sous-sequencement) — cette fonction se contente de fournir les deux
    valeurs calculees, la mise en forme/affichage simultane relevant de la
    couche ecran, pas de ce service."""
    return convert_textile_measurement(variant_id, length_m=length_m, weight_kg=weight_kg)


def create_reception_move_from_measurement(
    measurement: StkMeasurement,
    *,
    tenant: Tenant,
    variant_id: Any,
    location_from: StkLocation,
    location_to: StkLocation,
    date: dt.date,
    move_type: str = StkMove.TYPE_RECEPTION,
    source_document: str = "",
    unit_cost_mga: Decimal = Decimal(0),
    lot: StkLot | None = None,
    operator: User | None = None,
) -> StkMove:
    """Enveloppe de convenance autour de `services.moves.create_move` qui
    fait du "quantite mesuree, jamais theorique" (RG-STK-4) le chemin de
    moindre resistance, sans pour autant l'imposer structurellement (cf.
    docstring de module ci-dessus) : `qty`/`uom` sont TOUJOURS derives de
    `measurement.value`/`measurement.uom`, jamais parametrables
    independamment par l'appelant — un appelant qui construit une
    reception a partir d'un rouleau mesure n'a qu'a passer la
    `StkMeasurement` elle-meme plutot qu'un chiffre qu'il devrait
    recopier (et pourrait, par erreur, recopier depuis la valeur
    theorique/commandee au lieu de la valeur mesuree)."""
    return create_move(
        tenant=tenant,
        variant_id=variant_id,
        qty=measurement.value,
        uom=measurement.uom,
        location_from=location_from,
        location_to=location_to,
        date=date,
        move_type=move_type,
        source_document=source_document,
        unit_cost_mga=unit_cost_mga,
        lot=lot,
        operator=operator,
    )
