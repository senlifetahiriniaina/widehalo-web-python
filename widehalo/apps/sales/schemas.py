"""Schemas django-ninja de l'API `sales` (§5.5.7, S1 : devis, S2 :
commande de vente). Montants toujours `Decimal` (jamais `float`,
convention projet)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from ninja import Field, Schema


class QuotationLineIn(Schema):
    variant_id: UUID | None = None
    description: str = ""
    qty: Decimal = Decimal(1)
    uom: str = ""
    unit_price: Decimal | None = None
    discount_pct: Decimal = Decimal(0)
    is_custom: bool = False
    source: str = "stock"


class QuotationIn(Schema):
    """Les identifiants sont des `UUID`, pas des `str`.

    **Le défaut fermé, et il rendait 500.** L'endpoint faisait
    `uuid.UUID(payload.partner_id)` sur un champ déclaré `str` : une
    chaîne quelconque traversait la validation de schéma puis levait
    `ValueError` dans le corps de la vue, où plus rien ne la rattrapait.
    Typé `UUID`, c'est django-ninja qui refuse — 422, en nommant le champ,
    et l'OpenAPI annonce `format: uuid` à l'intégrateur.
    """

    partner_id: UUID
    date: dt.date
    contact: str = ""
    source_lead_id: UUID | None = None
    validity_date: dt.date | None = None
    pricelist_id: UUID | None = None
    currency: str = "MGA"
    payment_term_id: UUID | None = None
    incoterm: str = ""
    delivery_address: str = ""
    notes: str = ""
    internal_notes: str = ""
    lines: list[QuotationLineIn] = []


class QuotationDeclineIn(Schema):
    reason: str = ""


class QuotationLineOut(Schema):
    """RG-SAL-5 (S7) : `margin_pct`/`cost_estimate_mga` sont declares ici
    pour que le champ EXISTE dans le contrat d'API (l'acceptance test
    §5.5.8 n°4 exige qu'il soit present puis masque, pas simplement
    absent) — mais leur masquage effectif par role n'a pas lieu ici (une
    `Schema` ninja ne connait pas l'utilisateur courant) : il est applique
    en amont, sur le dict de sortie, par
    `apps.core.services.permissions.filter_fields_for_role` (cf.
    `apps.sales.api._serialize_line`). Les deux champs sont optionnels
    dans la reponse JSON pour un utilisateur sans le role requis."""

    id: str
    sequence: int
    variant_id: UUID | None
    is_custom: bool
    description: str
    qty: Decimal
    uom: str
    unit_price: Decimal
    discount_pct: Decimal
    subtotal: Decimal
    source: str
    margin_pct: Decimal | None = None
    cost_estimate_mga: Decimal | None = None


class QuotationOut(Schema):
    id: str
    reference: str
    partner_id: UUID
    contact: str
    source_lead_id: UUID | None
    source_lead_reference: str
    date: dt.date
    validity_date: dt.date | None
    currency: str
    incoterm: str
    state: str
    amount_untaxed: Decimal
    amount_tax: Decimal
    amount_total: Decimal
    amount_total_mga: Decimal
    notes: str
    lines: list[QuotationLineOut]


class OrderLineIn(Schema):
    variant_id: UUID | None = None
    description: str = ""
    qty: Decimal = Decimal(1)
    uom: str = ""
    unit_price: Decimal | None = None
    discount_pct: Decimal = Decimal(0)
    is_custom: bool = False
    source: str = "stock"
    billing_policy: str = "on_ordered_qty"
    deposit_pct: Decimal | None = None


class OrderIn(Schema):
    """Mêmes identifiants typés que `QuotationIn`, même motif."""

    partner_id: UUID
    date: dt.date
    quotation_id: UUID | None = None
    contact: str = ""
    source_lead_id: UUID | None = None
    commitment_date: dt.date | None = None
    pricelist_id: UUID | None = None
    currency: str = "MGA"
    payment_term_id: UUID | None = None
    incoterm: str = ""
    delivery_address: str = ""
    notes: str = ""
    internal_notes: str = ""
    lines: list[OrderLineIn] = []


class OrderCancelIn(Schema):
    reason: str = ""


class OrderDeliverIn(Schema):
    partial: bool = False


class OrderInvoiceIn(Schema):
    # Ids de `SalesOrderLine` a facturer (facturation partielle) ; liste
    # vide/omise = toutes les lignes de la commande. Typés `UUID` : la vue
    # les convertissait elle-même, et une chaîne quelconque y levait un
    # `ValueError` non rattrapé — donc un 500 pour une entrée invalide.
    line_ids: list[UUID] = []


class OrderInvoiceOut(Schema):
    invoice_id: UUID | None
    detail: str = ""


class OrderLineOut(Schema):
    id: str
    sequence: int
    variant_id: UUID | None
    is_custom: bool
    description: str
    qty: Decimal
    uom: str
    unit_price: Decimal
    discount_pct: Decimal
    subtotal: Decimal
    source: str
    qty_delivered: Decimal
    qty_invoiced: Decimal
    billing_policy: str
    deposit_pct: Decimal | None
    # RG-SAL-5 (S7) : meme masquage que `QuotationLineOut`, cf. sa docstring.
    margin_pct: Decimal | None = None
    cost_estimate_mga: Decimal | None = None


class RecurrenceIn(Schema):
    name: str
    interval: str
    start_date: dt.date
    template_order_id: UUID
    day_rule: str = ""
    end_date: dt.date | None = None


class RecurrenceOut(Schema):
    id: str
    name: str
    interval: str
    day_rule: str
    start_date: dt.date
    end_date: dt.date | None
    next_run: dt.date
    template_order_id: UUID
    is_active: bool


class ForecastOut(Schema):
    id: str
    period: str
    variant_id: UUID
    partner_id: UUID | None
    qty_forecast: Decimal
    qty_actual: Decimal | None
    confidence: str
    method: str
    computed_at: dt.datetime
    parameters: dict[str, Any]


class ForecastRecomputeIn(Schema):
    period: str


class TargetIn(Schema):
    """L'objectif commercial, borné par son schéma plutôt que par la base.

    **Trois 500 fermés d'un coup.** `POST /sales/targets` faisait
    `SalesTarget.objects.create(**payload)` sans validation : une `period`
    de plus de sept caractères, un `amount_mga` au-delà de dix-huit
    chiffres, ou un `scope` hors des trois valeurs déclarées passaient la
    vue et faisaient lever Postgres — `DataError`, donc 500. Les deux
    premiers sont désormais refusés ICI, par le schéma ; le troisième
    l'est par `SalesTarget.save()`, parce qu'un `choices` que rien ne
    vérifie est un `choices` décoratif, et qu'il y a d'autres portes que
    cet endpoint.

    `period` est le bucket mensuel « AAAA-MM », le même format que
    `SalesForecast.period` — un motif, pas une date, parce que la colonne
    est un `CharField(max_length=7)` et non un `DateField`."""

    period: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    scope: Literal["company", "team", "salesperson"] = "company"
    scope_ref: UUID | None = None
    amount_mga: Decimal = Field(default=Decimal(0), max_digits=18, decimal_places=4)
    qty: Decimal | None = Field(default=None, max_digits=18, decimal_places=4)


class TargetOut(Schema):
    id: str
    period: str
    scope: str
    scope_ref: str | None
    amount_mga: Decimal
    qty: Decimal | None


class OrderOut(Schema):
    id: str
    reference: str
    quotation_id: UUID | None
    partner_id: UUID
    contact: str
    source_lead_id: UUID | None
    source_lead_reference: str
    date: dt.date
    date_confirmed: dt.date | None
    commitment_date: dt.date | None
    currency: str
    incoterm: str
    state: str
    blocked_reason: str
    cancel_reason: str
    amount_untaxed: Decimal
    amount_tax: Decimal
    amount_total: Decimal
    amount_total_mga: Decimal
    notes: str
    is_recurring: bool
    invoiced_amount_mga: Decimal
    lines: list[OrderLineOut]
