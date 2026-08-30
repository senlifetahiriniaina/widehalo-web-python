"""LOG5 : dossier douanier, calculateur de droits de douane (RG-LOG-6),
transfert des couts d'approche a la cloture (RG-LOG-7, reel — plus aucun
stub, `stocks` existe desormais) et retard d'expedition -> incident achats
(RG-LOG-9, nouveau gap `purchase.services.public.open_purchase_incident`).

Formule RG-LOG-6 (calculateur autonome, entierement autoporte) :
- Valeur CAF = FOB + Fret + Assurance.
- Droits = CAF x taux SH (`LogHsCode.duty_rate_pct`).
- Base TVA = CAF + Droits + autres taxes non recuperables.
- TVA import = Base TVA x taux TVA (20% par defaut, PCG 2005 Madagascar —
  parametrable, jamais fige en dur au-dela de la valeur par defaut).
- Cout de revient = FOB + Fret + Assurance + Droits + Taxes non
  recuperables + Transit (jamais la TVA, recuperable pour un assujetti)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.accounting.services.public import create_landed_cost_batch_from_source
from apps.logistics.models import LogCustomsFile, LogCustomsLine, LogHsCode, LogShipment
from apps.logistics.services.ai_anomaly_registration import OPEN_TOO_LONG_DAYS
from apps.purchase.services.public import open_purchase_incident
from apps.stocks.services.public import apply_landed_cost_to_valuation

if TYPE_CHECKING:
    from apps.core.models.risk import RiskItem
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User

DEFAULT_VAT_RATE_PCT = Decimal("20")


def create_hs_code(
    tenant: Tenant,
    *,
    code: str,
    description: str,
    duty_rate_pct: Decimal,
    valid_from: dt.date | None = None,
    valid_to: dt.date | None = None,
) -> LogHsCode:
    hs_code = LogHsCode(
        tenant=tenant,
        code=code,
        description=description,
        duty_rate_pct=duty_rate_pct,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    hs_code.full_clean()
    hs_code.save()
    return hs_code


def simulate_customs_duties(
    *,
    fob_value_mga: Decimal,
    duty_rate_pct: Decimal,
    freight_value_mga: Decimal = Decimal(0),
    insurance_value_mga: Decimal = Decimal(0),
    other_non_recoverable_taxes_mga: Decimal = Decimal(0),
    transit_cost_mga: Decimal = Decimal(0),
    vat_rate_pct: Decimal = DEFAULT_VAT_RATE_PCT,
) -> dict[str, Decimal]:
    """RG-LOG-6 : calculateur pur (aucun acces base), utilise a la fois par
    `add_customs_line` (calcul persiste sur la ligne) et par un futur
    endpoint `POST .../customs/simulate` (apercu avant creation reelle)."""
    caf_value_mga = fob_value_mga + freight_value_mga + insurance_value_mga
    duty_mga = caf_value_mga * duty_rate_pct / Decimal(100)
    vat_base_mga = caf_value_mga + duty_mga + other_non_recoverable_taxes_mga
    vat_mga = vat_base_mga * vat_rate_pct / Decimal(100)
    landed_cost_mga = (
        fob_value_mga
        + freight_value_mga
        + insurance_value_mga
        + duty_mga
        + other_non_recoverable_taxes_mga
        + transit_cost_mga
    )
    return {
        "caf_value_mga": caf_value_mga,
        "duty_mga": duty_mga,
        "vat_base_mga": vat_base_mga,
        "vat_mga": vat_mga,
        "landed_cost_mga": landed_cost_mga,
    }


def create_customs_file(
    tenant: Tenant, *, shipment: LogShipment, broker: Any = None, opened_at: dt.date | None = None
) -> LogCustomsFile:
    customs_file = LogCustomsFile(
        tenant=tenant,
        shipment=shipment,
        broker=broker,
        opened_at=opened_at or dt.date.today(),
    )
    customs_file.full_clean()
    customs_file.save()
    return customs_file


def add_customs_line(
    customs_file: LogCustomsFile,
    *,
    hs_code: LogHsCode,
    description: str,
    fob_value_mga: Decimal,
    freight_value_mga: Decimal = Decimal(0),
    insurance_value_mga: Decimal = Decimal(0),
    other_non_recoverable_taxes_mga: Decimal = Decimal(0),
    transit_cost_mga: Decimal = Decimal(0),
    qty: Decimal = Decimal(1),
    weight_kg: Decimal | None = None,
    variant_id: Any = None,
) -> LogCustomsLine:
    result = simulate_customs_duties(
        fob_value_mga=fob_value_mga,
        duty_rate_pct=hs_code.duty_rate_pct,
        freight_value_mga=freight_value_mga,
        insurance_value_mga=insurance_value_mga,
        other_non_recoverable_taxes_mga=other_non_recoverable_taxes_mga,
        transit_cost_mga=transit_cost_mga,
    )
    line = LogCustomsLine(
        tenant=customs_file.tenant,
        customs_file=customs_file,
        hs_code=hs_code,
        description=description,
        variant_id=variant_id,
        qty=qty,
        weight_kg=weight_kg,
        fob_value_mga=fob_value_mga,
        freight_value_mga=freight_value_mga,
        insurance_value_mga=insurance_value_mga,
        other_non_recoverable_taxes_mga=other_non_recoverable_taxes_mga,
        transit_cost_mga=transit_cost_mga,
        **result,
    )
    line.full_clean()
    line.save()
    return line


def close_customs_file(customs_file: LogCustomsFile) -> LogCustomsFile:
    """RG-LOG-7 : transfere les couts d'approche reels (droits + taxes non
    recuperables + transit — jamais la TVA, recuperable) vers une vraie
    ecriture comptable (`accounting.services.public.
    create_landed_cost_batch_from_source`, deja construit A17/PU6, aucune
    nouvelle brique comptable) ET met a jour REELLEMENT la valorisation du
    stock (`stocks.services.public.apply_landed_cost_to_valuation`) pour
    chaque ligne reliee a une variante — plus aucun stub, contrairement a
    la version initialement envisagee de ce chantier."""
    if customs_file.state != LogCustomsFile.STATE_CLEARED:
        raise ValidationError(
            _("Le dossier douanier doit etre au statut « dedouane » avant d'etre cloture.")
        )

    lines = list(customs_file.lines.all())
    landed_lines = [
        {
            "description": line.description,
            "qty": line.qty,
            "purchase_value_mga": line.fob_value_mga,
            "variant_id": line.variant_id,
            "weight_kg": line.weight_kg,
        }
        for line in lines
    ]
    cost_components: list[dict[str, Any]] = [
        {
            "label": "Droits de douane",
            "amount_mga": sum((line.duty_mga for line in lines), Decimal(0)),
        },
        {
            "label": "Taxes non recuperables",
            "amount_mga": sum((line.other_non_recoverable_taxes_mga for line in lines), Decimal(0)),
        },
        {
            "label": "Transit",
            "amount_mga": sum((line.transit_cost_mga for line in lines), Decimal(0)),
        },
    ]
    batch_id = create_landed_cost_batch_from_source(
        tenant=customs_file.tenant,
        label=f"Dossier douanier {customs_file.reference or customs_file.id}",
        date=dt.date.today(),
        allocation_method="by_value",
        lines=landed_lines,
        cost_components=[c for c in cost_components if c["amount_mga"] > 0],
    )
    customs_file.landed_cost_batch_id = batch_id

    for line in lines:
        if line.variant_id is not None:
            additional_cost = (
                line.duty_mga + line.other_non_recoverable_taxes_mga + line.transit_cost_mga
            )
            if additional_cost > 0:
                apply_landed_cost_to_valuation(line.variant_id, additional_cost_mga=additional_cost)

    customs_file.state = LogCustomsFile.STATE_CLOSED
    customs_file.closed_at = dt.date.today()
    customs_file.save(update_fields=["state", "closed_at", "landed_cost_batch_id"])
    return customs_file


def mark_customs_file_cleared(customs_file: LogCustomsFile) -> LogCustomsFile:
    if customs_file.state != LogCustomsFile.STATE_OPEN:
        raise ValidationError(_("Le dossier douanier doit etre ouvert pour etre dedouane."))
    customs_file.state = LogCustomsFile.STATE_CLEARED
    customs_file.cleared_at = dt.date.today()
    customs_file.save(update_fields=["state", "cleared_at"])
    return customs_file


def flag_customs_file_risk(
    customs_file: LogCustomsFile, *, owner: User, mitigation_plan: str = ""
) -> RiskItem | None:
    """INT3 (chantier interactivite native inter-modules) : transforme un
    dossier douanier REELLEMENT a risque en `RiskItem` generique
    (`core.services.risk.create_risk_item`, RSK1-2) — reutilise
    EXACTEMENT le meme seuil que l'anomalie deterministe
    `logistics.customs_file_at_risk` (`OPEN_TOO_LONG_DAYS`, cf.
    `apps.logistics.services.ai_anomaly_registration`, INT2), jamais un
    second calcul divergent. Retourne `None` (jamais d'exception) si le
    dossier n'est PAS a risque — un dossier `cleared`/`closed`, ou encore
    `open` mais pas assez vieux, est le cas NORMAL, pas une erreur d'appel
    (meme discipline que `report_shipment_delay` ci-dessous qui renvoie
    `None` "trop tot").

    **Jamais automatique sur chaque changement d'etat** : ni
    `mark_customs_file_cleared` ni `close_customs_file` n'appellent cette
    fonction — un dossier qui progresse normalement (`open -> cleared ->
    closed` avant `OPEN_TOO_LONG_DAYS`) ne doit jamais generer de
    `RiskItem` (ce serait du bruit sur le cas normal). Point d'entree
    explicite (vue/action manuelle, ou verification periodique) a appeler
    quand on veut MATERIALISER en risque suivi ce que l'anomalie
    deterministe a deja detecte en LECTURE SEULE.

    Score assume : `impact=4` (immobilisation/surcout, toujours
    significatif pour un dossier bloque) ; `likelihood=5` si le dossier
    est ouvert depuis au moins `2 x OPEN_TOO_LONG_DAYS` jours (meme palier
    "severite haute" que l'anomalie), sinon `likelihood=3` — meme
    granularite a 2 paliers que `SEVERITY_HIGH`/`SEVERITY_MEDIUM` de
    `ai_anomaly_registration`. `owner` doit etre fourni par l'appelant
    (`LogCustomsFile` ne porte aucun champ utilisateur exploitable : seul
    `broker` existe, une FK `LogServiceProvider`, jamais un `core.User`)."""
    if customs_file.state != LogCustomsFile.STATE_OPEN:
        return None

    age_days = (dt.date.today() - customs_file.opened_at).days
    if age_days < OPEN_TOO_LONG_DAYS:
        return None

    from apps.core.models.risk import CATEGORY_LOGISTICS
    from apps.core.services.risk import create_risk_item

    likelihood = 5 if age_days >= OPEN_TOO_LONG_DAYS * 2 else 3
    return create_risk_item(
        tenant=customs_file.tenant,
        category=CATEGORY_LOGISTICS,
        likelihood=likelihood,
        impact=4,
        owner=owner,
        mitigation_plan=mitigation_plan,
        content_object=customs_file,
    )


def report_shipment_delay(
    shipment: LogShipment,
    *,
    expected_date: dt.date,
    supplier_partner_id: Any,
    as_of: dt.date | None = None,
    threshold_days: int = 3,
) -> Any:
    """RG-LOG-9 : au-dela de `threshold_days` de retard par rapport a
    `expected_date`, ouvre un incident fournisseur (gap
    `purchase.services.public.open_purchase_incident`, deja construit PU7)
    plutot qu'une simple alerte muette. Retourne `None`, jamais une
    exception, si le retard n'est pas encore avere — un appel "trop tot"
    n'est pas une erreur, c'est le cas normal d'une verification
    periodique."""
    as_of = as_of or dt.date.today()
    delay_days = (as_of - expected_date).days
    if delay_days <= threshold_days:
        return None

    return open_purchase_incident(
        tenant=shipment.tenant,
        type="retard",
        partner_id=supplier_partner_id,
        description=(
            f"Expedition {shipment.reference or shipment.id} en retard de {delay_days} "
            f"jour(s) par rapport a la date attendue ({expected_date})."
        ),
        impact=f"Retard de {delay_days} jours",
    )
