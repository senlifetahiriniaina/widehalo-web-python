"""A15 — reconciliation mobile money SIMPLE, PAS le moteur de rapprochement
bancaire generique a regles d'A16 (`acc_reconcile_rule`, import OFX/CSV,
moteur montant/reference/tiers) : ce module est un mecanisme autonome et
plus simple, dedie exclusivement au rapprochement des `AccPayment.method
="mobile_money"` avec un relevé importe.

Reserve legere documentee (meme discipline que les formules de
`services/reports.py::financial_ratios`, A13, pas la reserve DGI plus
lourde des canevas fiscaux) : le format CSV ci-dessous (`date`, `reference`,
`amount`, `direction`) est un format PLACEHOLDER retenu en l'absence de
specification d'un export reel Mvola/Orange Money/Airtel Money (operateurs
mobile money malgaches, cf. `COUNTRY_DEFAULTS["MG"]` du Lot 1) — a ajuster
des qu'un export reel d'un de ces operateurs sera obtenu.

V1 : rapprochement MANUEL/ASSISTE uniquement (`reconcile_mobile_money_line`
prend `payment` en parametre explicite) — aucune correspondance floue
automatique (proximite montant/date) n'est construite ici, cf. le mot
"simple" du plan lui-meme ("reconciliation mobile money simple")."""

from __future__ import annotations

import csv
import datetime as dt
import io
import uuid
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.accounting.models import AccMobileMoneyStatementLine, AccPayment
from apps.core.models.tenant import Tenant


def import_mobile_money_statement(
    tenant: Tenant, csv_bytes: bytes
) -> list[AccMobileMoneyStatementLine]:
    """Parse un CSV placeholder (colonnes `date` ISO YYYY-MM-DD, `reference`,
    `amount`, `direction` in/out) et cree une `AccMobileMoneyStatementLine`
    par ligne, toutes dans le meme `import_batch_id` (un `uuid4()` genere ici,
    partage par tout l'import), `state="unmatched"`."""
    batch_id = uuid.uuid4()
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8")))
    lines: list[AccMobileMoneyStatementLine] = []
    for row in reader:
        try:
            amount = Decimal(row["amount"])
        except (KeyError, InvalidOperation) as exc:
            raise ValidationError(
                _("Montant invalide dans le relevé mobile money : %(value)r")
                % {"value": row.get("amount")}
            ) from exc
        try:
            statement_date = dt.date.fromisoformat(row["date"])
        except (KeyError, ValueError) as exc:
            raise ValidationError(
                _("Date invalide dans le relevé mobile money : %(value)r")
                % {"value": row.get("date")}
            ) from exc
        direction = row.get("direction", "").strip()
        if direction not in (
            AccMobileMoneyStatementLine.DIRECTION_IN,
            AccMobileMoneyStatementLine.DIRECTION_OUT,
        ):
            raise ValidationError(
                _("Sens de transaction invalide dans le relevé mobile money : %(value)r")
                % {"value": direction}
            )
        lines.append(
            AccMobileMoneyStatementLine.objects.create(
                tenant=tenant,
                import_batch_id=batch_id,
                statement_date=statement_date,
                reference_external=row.get("reference", ""),
                amount_mga=amount,
                direction=direction,
                state=AccMobileMoneyStatementLine.STATE_UNMATCHED,
            )
        )
    return lines


def reconcile_mobile_money_line(
    statement_line: AccMobileMoneyStatementLine, payment: AccPayment
) -> AccMobileMoneyStatementLine:
    """Rapproche manuellement `statement_line` avec `payment` — refuse si
    `payment.method != "mobile_money"` (RG implicite : un paiement especes/
    virement/cheque n'a pas sa place dans ce rapprochement dedie)."""
    if payment.method != AccPayment.METHOD_MOBILE_MONEY:
        raise ValidationError(
            _("Seul un paiement de méthode mobile money peut être rapproche ici.")
        )
    statement_line.matched_payment = payment
    statement_line.state = AccMobileMoneyStatementLine.STATE_MATCHED
    statement_line.save(update_fields=["matched_payment", "state"])
    return statement_line


def unmatched_mobile_money_lines(tenant: Tenant) -> list[AccMobileMoneyStatementLine]:
    """Liste plate des lignes non encore rapprochees — pour un futur ecran
    de rapprochement assiste. `tenant` : cf. note de
    `services/reports.py::treasury_forecast` sur `TenantManager`, non
    utilise directement pour filtrer (deja assure par le manager)."""
    del tenant
    return list(
        AccMobileMoneyStatementLine.objects.filter(
            state=AccMobileMoneyStatementLine.STATE_UNMATCHED
        ).order_by("statement_date")
    )


__all__ = [
    "import_mobile_money_statement",
    "reconcile_mobile_money_line",
    "unmatched_mobile_money_lines",
]
