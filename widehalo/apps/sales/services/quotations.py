"""Devis (§5.5.2, S1 du sous-sequencement `sales`) : creation rapide,
lignes resolues sur le catalogue (prix cascade contrat>client>defaut via
`catalog.services.public.get_variant_price`) ou hors catalogue
(`is_custom`, comme `crm.CrmLeadLine`/`accounting`), et workflow simple
`draft -> sent -> accepted/declined -> expired` (pas de FSM `django-fsm` en
S1 : le CDC ne specifie un workflow complet que pour `sales_order`, cf.
plan — S2 introduira la vraie machine a etats sur `SalesOrder`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.services.public import get_variant_price
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.sales.models import SalesQuotation, SalesQuotationLine
from apps.sales.services.taxes import document_tax_total, resolve_line_tax


def create_quotation(
    *,
    tenant: Tenant,
    partner_id: UUID,
    date: dt.date,
    salesperson: User | None = None,
    currency: str = "MGA",
    source_lead_id: UUID | None = None,
    reference: str = "",
    **optional_fields: Any,
) -> SalesQuotation:
    """Chantier "numero de document modifiable" (DT4) : `reference` reste
    optionnel — vide (comportement par defaut, tous les appelants
    existants), `next_reference()` s'applique inchange. Renseigne, la
    valeur saisie est utilisee TELLE QUELLE apres verification d'unicite
    par tenant (`ReferenceMixin.reference` n'a aucune contrainte d'unicite
    en base, `db_index=True` seulement — cf. `apps.core.models.base` — donc
    la collision doit etre revalidee explicitement ici). **Jamais** de
    pre-remplissage cote serveur avec un "prochain numero suggere" :
    `next_reference()` verrouille et incremente une sequence a chaque
    appel, la consommer au simple chargement d'un formulaire jamais
    soumis creerait des trous dans la numerotation — cette fonction n'est
    donc appelee qu'ici, au moment reel de la creation."""
    reference = reference.strip()
    if reference:
        if SalesQuotation.objects.filter(tenant=tenant, reference=reference).exists():
            raise ValidationError(
                _("Un devis avec la référence %(reference)s existe déjà.")
                % {"reference": reference}
            )
    else:
        reference = next_reference(tenant, "DEVIS", timezone.now().year)
    return SalesQuotation.objects.create(
        tenant=tenant,
        reference=reference,
        partner_id=partner_id,
        date=date,
        salesperson=salesperson,
        currency=currency,
        source_lead_id=source_lead_id,
        **optional_fields,
    )


def add_quotation_line(
    quotation: SalesQuotation,
    *,
    variant_id: UUID | None = None,
    description: str,
    qty: Decimal,
    uom: str = "",
    unit_price: Decimal | None = None,
    discount_pct: Decimal = Decimal(0),
    is_custom: bool = False,
    **optional_fields: Any,
) -> SalesQuotationLine:
    if not is_custom and variant_id is not None and unit_price is None:
        unit_price = get_variant_price(variant_id, partner_id=quotation.partner_id)
    unit_price = unit_price or Decimal(0)

    subtotal = (qty * unit_price * (Decimal(100) - discount_pct) / Decimal(100)).quantize(
        Decimal("0.0001")
    )

    # L5 : la taxe est FIGEE ici, a la date du devis (jamais « aujourd'hui »,
    # cf. `services.taxes.resolve_line_tax`). Un `tax_id` explicite fourni
    # par l'appelant l'emporte ; son taux est relu sur cette taxe-la, jamais
    # recopie depuis un parametre.
    tax_id, tax_rate = resolve_line_tax(
        quotation.tenant, on_date=quotation.date, tax_id=optional_fields.pop("tax_id", None)
    )

    line = SalesQuotationLine.objects.create(
        tenant=quotation.tenant,
        quotation=quotation,
        variant_id=variant_id,
        description=description,
        qty=qty,
        uom=uom,
        unit_price=unit_price,
        discount_pct=discount_pct,
        tax_id=tax_id,
        tax_rate=tax_rate,
        subtotal=subtotal,
        is_custom=is_custom,
        **optional_fields,
    )
    _recompute_totals(quotation)
    return line


def _recompute_totals(quotation: SalesQuotation) -> None:
    """Recalcule les montants totaux du devis a partir de ses lignes.

    L5 : `amount_tax` n'est plus force a zero. Il est la somme des TVA
    figees ligne a ligne (`SalesQuotationLine.tax_rate`), jamais un
    recalcul depuis `AccTax` — un devis emis sous l'ancien taux garde le
    sien meme apres une loi de finances. `amount_total` devient donc le
    TTC : c'est le montant que le client signe, et celui qu'il devra."""
    amount_untaxed, amount_tax = document_tax_total(quotation.lines)
    quotation.amount_untaxed = amount_untaxed
    quotation.amount_tax = amount_tax
    quotation.amount_total = amount_untaxed + amount_tax
    # Pas de conversion de change reelle en S1 (le taux du jour vit dans
    # `accounting.AccExchangeRate`, non expose en `services.public` — hors
    # perimetre de ce lot) : `amount_total_mga` reprend `amount_total` tel
    # quel, ce qui est exact quand `currency == "MGA"` (cas par defaut) et
    # une approximation documentee sinon, a corriger quand `sales`
    # consommera un futur gap de change public.
    quotation.amount_total_mga = quotation.amount_total
    quotation.save(
        update_fields=["amount_untaxed", "amount_tax", "amount_total", "amount_total_mga"]
    )


def send_quotation(quotation: SalesQuotation) -> SalesQuotation:
    if quotation.state != SalesQuotation.STATE_DRAFT:
        raise ValidationError(_("Seul un devis brouillon peut être envoyé."))
    quotation.state = SalesQuotation.STATE_SENT
    quotation.save(update_fields=["state"])
    return quotation


def accept_quotation(quotation: SalesQuotation) -> SalesQuotation:
    if quotation.state != SalesQuotation.STATE_SENT:
        raise ValidationError(_("Seul un devis envoyé peut être accepte."))
    quotation.state = SalesQuotation.STATE_ACCEPTED
    quotation.save(update_fields=["state"])
    return quotation


def decline_quotation(quotation: SalesQuotation, *, reason: str = "") -> SalesQuotation:
    if quotation.state != SalesQuotation.STATE_SENT:
        raise ValidationError(_("Seul un devis envoyé peut être refuse."))
    quotation.state = SalesQuotation.STATE_DECLINED
    if reason:
        quotation.internal_notes = (
            f"{quotation.internal_notes}\n{reason}" if quotation.internal_notes else reason
        )
        quotation.save(update_fields=["state", "internal_notes"])
    else:
        quotation.save(update_fields=["state"])
    return quotation


def expire_quotation(quotation: SalesQuotation) -> SalesQuotation:
    if quotation.state != SalesQuotation.STATE_SENT:
        raise ValidationError(_("Seul un devis envoyé peut expirer."))
    quotation.state = SalesQuotation.STATE_EXPIRED
    quotation.save(update_fields=["state"])
    return quotation
