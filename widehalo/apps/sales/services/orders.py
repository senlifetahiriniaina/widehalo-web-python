"""Commande de vente (§5.5.2/5.5.4, S2 du sous-sequencement `sales`, cf.
plan) : creation directe ou depuis un devis accepte (RG-SAL-1, chaine
documentaire sans ressaisie), controle de credit a la confirmation
(RG-SAL-4), et machine a etats complete du §5.5.4 (`SalesOrder.state`,
`django-fsm-2`/`attempt_transition()` du socle, meme patron que
`AccMove.invoice_state`/`MrpOrder.state`). `confirm_order()` declenche
aussi, une fois la confirmation effective (jamais sur une commande
`blocked`), la qualification d'origine par ligne RG-SAL-3 (S3, cf.
`apps.sales.services.procurement`).

RG-SAL-2 (facturation reelle) est differee a S4 : `mark_invoiced`/`close`
restent declarees sur le modele mais aucune fonction de service reelle ne
les declenche encore ici (cf. tests, qui exercent ces aretes directement
via `attempt_transition` pour la couverture FSM)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.catalog.services.public import get_variant_price
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.sequences import next_reference
from apps.core.services.workflow import attempt_transition
from apps.partners.services.public import is_over_credit_limit
from apps.sales.models import SalesOrder, SalesOrderLine, SalesQuotation
from apps.sales.services import procurement


def create_order(
    *,
    tenant: Tenant,
    partner_id: UUID,
    date: dt.date,
    salesperson: User | None = None,
    currency: str = "MGA",
    source_lead_id: UUID | None = None,
    **optional_fields: Any,
) -> SalesOrder:
    """Creation directe (sans devis prealable) — meme forme que
    `quotations.create_quotation`."""
    reference = next_reference(tenant, "CMD", timezone.now().year)
    return SalesOrder.objects.create(
        tenant=tenant,
        reference=reference,
        partner_id=partner_id,
        date=date,
        salesperson=salesperson,
        currency=currency,
        source_lead_id=source_lead_id,
        **optional_fields,
    )


def create_order_from_quotation(quotation: SalesQuotation) -> SalesOrder:
    """RG-SAL-1 : chaine documentaire, aucune ressaisie — copie les
    donnees du devis (partenaire, tarification, lignes) sans jamais
    demander a l'appelant de les refournir. Seul un devis `accepted` peut
    etre transforme."""
    if quotation.state != SalesQuotation.STATE_ACCEPTED:
        raise ValidationError(_("Seul un devis accepte peut etre transforme en commande."))

    reference = next_reference(quotation.tenant, "CMD", timezone.now().year)
    order = SalesOrder.objects.create(
        tenant=quotation.tenant,
        reference=reference,
        quotation=quotation,
        partner_id=quotation.partner_id,
        contact=quotation.contact,
        source_lead_id=quotation.source_lead_id,
        date=timezone.now().date(),
        pricelist_id=quotation.pricelist_id,
        currency=quotation.currency,
        payment_term_id=quotation.payment_term_id,
        incoterm=quotation.incoterm,
        delivery_address=quotation.delivery_address,
        salesperson=quotation.salesperson,
        notes=quotation.notes,
        internal_notes=quotation.internal_notes,
    )
    for line in quotation.lines.all():
        SalesOrderLine.objects.create(
            tenant=order.tenant,
            order=order,
            sequence=line.sequence,
            variant_id=line.variant_id,
            is_custom=line.is_custom,
            description=line.description,
            qty=line.qty,
            uom=line.uom,
            unit_price=line.unit_price,
            discount_pct=line.discount_pct,
            tax_id=line.tax_id,
            subtotal=line.subtotal,
            cost_estimate_mga=line.cost_estimate_mga,
            margin_pct=line.margin_pct,
            lead_time_days=line.lead_time_days,
            source=line.source,
        )
    _recompute_totals(order)
    return order


def add_order_line(
    order: SalesOrder,
    *,
    variant_id: UUID | None = None,
    description: str,
    qty: Decimal,
    uom: str = "",
    unit_price: Decimal | None = None,
    discount_pct: Decimal = Decimal(0),
    is_custom: bool = False,
    **optional_fields: Any,
) -> SalesOrderLine:
    if not is_custom and variant_id is not None and unit_price is None:
        unit_price = get_variant_price(variant_id, partner_id=order.partner_id)
    unit_price = unit_price or Decimal(0)

    subtotal = (qty * unit_price * (Decimal(100) - discount_pct) / Decimal(100)).quantize(
        Decimal("0.0001")
    )

    line = SalesOrderLine.objects.create(
        tenant=order.tenant,
        order=order,
        variant_id=variant_id,
        description=description,
        qty=qty,
        uom=uom,
        unit_price=unit_price,
        discount_pct=discount_pct,
        subtotal=subtotal,
        is_custom=is_custom,
        **optional_fields,
    )
    _recompute_totals(order)
    return line


def _recompute_totals(order: SalesOrder) -> None:
    """Recalcule les montants totaux de la commande a partir de ses
    lignes — meme simplification assumee que
    `quotations._recompute_totals` (pas de calcul de taxe reel, pas de
    conversion de change reelle en S2)."""
    amount_untaxed = order.lines.aggregate(total=Sum("subtotal"))["total"] or Decimal(0)
    order.amount_untaxed = amount_untaxed
    order.amount_tax = Decimal(0)
    order.amount_total = amount_untaxed
    order.amount_total_mga = amount_untaxed
    order.save(update_fields=["amount_untaxed", "amount_tax", "amount_total", "amount_total_mga"])


def send_order(order: SalesOrder, user: User) -> SalesOrder:
    attempt_transition(order, "send", user)
    order.save(update_fields=["state"])
    return order


def confirm_order(order: SalesOrder, user: User) -> SalesOrder:
    """RG-SAL-4 : controle de credit a la confirmation. `sales` calcule
    son propre encours (le CDC ne fournit pas de formule exacte, la
    definition retenue est documentee ici) et delegue le seuil a
    `partners.services.public.is_over_credit_limit`.

    Definition d'encours retenue : somme de `amount_total_mga` de toutes
    les autres commandes du meme partenaire deja engagees mais pas encore
    facturees (`confirmed`, `in_preparation`, `partially_delivered`,
    `delivered`), plus le montant de cette commande elle-meme — une fois
    facturee (S4), une commande sort de cet encours puisqu'elle bascule
    en creance comptable suivie par `accounting`, pas par `sales`.

    Un depassement ne leve PAS d'exception : `blocked` est un etat normal
    du diagramme §5.5.4, pas une erreur — la commande y est simplement
    transitionnee avec un motif trace, et la fonction retourne
    normalement."""
    outstanding = SalesOrder.objects.filter(
        tenant=order.tenant,
        partner_id=order.partner_id,
        state__in=[
            SalesOrder.STATE_CONFIRMED,
            SalesOrder.STATE_IN_PREPARATION,
            SalesOrder.STATE_PARTIALLY_DELIVERED,
            SalesOrder.STATE_DELIVERED,
        ],
    ).exclude(pk=order.pk).aggregate(total=Sum("amount_total_mga"))["total"] or Decimal(0)
    outstanding_amount_mga = outstanding + order.amount_total_mga

    if is_over_credit_limit(order.partner_id, outstanding_amount_mga):
        reason = _("Plafond de credit depasse")
        attempt_transition(order, "block_for_credit", user, comment=reason)
        order.blocked_reason = reason
        order.save(update_fields=["state", "blocked_reason"])
        return order

    attempt_transition(order, "confirm", user)
    order.date_confirmed = timezone.now().date()
    order.save(update_fields=["state", "date_confirmed"])

    # RG-SAL-3 (S3) : qualification d'origine par ligne, uniquement une
    # fois la commande effectivement confirmee — jamais sur une commande
    # `blocked` (cf. `apps.sales.services.procurement`).
    procurement.qualify_and_process_order(order, user)
    return order


def unblock_order(order: SalesOrder, user: User) -> SalesOrder:
    """Leve manuellement un blocage credit (ex. derogation manager) —
    aucune logique supplementaire en S2, simple transition."""
    attempt_transition(order, "unblock", user)
    order.save(update_fields=["state"])
    return order


def start_preparation(order: SalesOrder, user: User) -> SalesOrder:
    attempt_transition(order, "start_preparation", user)
    order.save(update_fields=["state"])
    return order


def mark_delivered(order: SalesOrder, user: User, *, partial: bool = False) -> SalesOrder:
    """Simplification assumee (S2, pas encore de `stocks`) : aucune
    integration entrepot reelle. Une livraison complete recopie
    naivement `qty_delivered = qty` sur chaque ligne ; une livraison
    partielle se contente de changer l'etat, le detail quantite par
    quantite restant a la charge d'un futur module `stocks`."""
    if partial:
        attempt_transition(order, "mark_partially_delivered", user)
        order.save(update_fields=["state"])
        return order

    attempt_transition(order, "mark_delivered", user)
    order.save(update_fields=["state"])
    for line in order.lines.all():
        line.qty_delivered = line.qty
        line.save(update_fields=["qty_delivered"])
    return order


def close_order(order: SalesOrder, user: User) -> SalesOrder:
    attempt_transition(order, "close", user)
    order.save(update_fields=["state"])
    return order


def cancel_order(order: SalesOrder, user: User, *, reason: str) -> SalesOrder:
    """Motif obligatoire (meme garde que
    `accounting.services.invoices.cancel_invoice`) — une commande deja
    `delivered`/`invoiced`/`closed` ne peut plus etre annulee directement."""
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour annuler une commande."))
    non_cancellable_states = (
        SalesOrder.STATE_DELIVERED,
        SalesOrder.STATE_INVOICED,
        SalesOrder.STATE_CLOSED,
    )
    if order.state in non_cancellable_states:
        raise ValidationError(
            _("Une commande livree, facturee ou cloturee ne peut plus etre annulee directement.")
        )

    attempt_transition(order, "cancel", user, comment=reason)
    order.cancel_reason = reason
    order.save(update_fields=["state", "cancel_reason"])
    return order
