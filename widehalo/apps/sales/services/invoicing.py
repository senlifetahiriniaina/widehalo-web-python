"""RG-SAL-2 (politique de facturation par ligne, §5.5.3) et SAL-AVCT1
(facturation a l'avancement de production, §5.5.9) — S4 du
sous-sequencement `sales` (cf. plan). Cable enfin la transition
`SalesOrder.mark_invoiced` declaree des S2 mais jamais encore
declenchee.

Simplification assumee pour `on_deposit` (documentee en detail sur
`invoiceable_amount_for_line`) : le CDC decrit "les acomptes generent une
facture d'acompte imputee a la facture finale", ce qui suggererait un
vrai lettrage entre deux `AccMove` distincts. Ce lot ne construit PAS ce
lettrage comptable (differe a un futur enrichissement `accounting`) : il
se contente de suivre, par ligne, la part deja facturee via le champ
existant `SalesOrderLine.qty_invoiced` (reinterprete ici comme une
quantite-equivalente deja facturee, cf. `_already_invoiced_amount`), ce
qui suffit a rendre le calcul idempotent et a ne jamais facturer deux
fois la meme part — sans fabriquer un mecanisme de "facture d'imputation"
distinct."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting.services.public import create_customer_invoice_from_source
from apps.core.models.user import User
from apps.core.services.notifications import dispatch_notification
from apps.core.services.workflow import attempt_transition
from apps.mrp.services.public import get_order_produced_qty
from apps.sales.models import SalesOrder, SalesOrderLine

# Tolerance sur l'egalite `invoiced_amount_mga` / `amount_total_mga` avant
# de considerer une commande entierement facturee — evite qu'un arrondi
# de calcul (division qty/subtotal, conversions de devise) empeche
# indefiniment le passage a `invoiced`. Le meme ordre de grandeur que les
# arrondis `Decimal("0.0001")` deja utilises dans `services.orders`.
_FULLY_INVOICED_TOLERANCE_MGA = Decimal("0.01")


def _already_invoiced_amount(line: SalesOrderLine) -> Decimal:
    """`qty_invoiced` est un champ de quantite (pas de montant), mais
    aucun nouveau champ de suivi n'est introduit pour rester minimal (cf.
    docstring module) : on le reinterprete comme une quantite-equivalente
    deja facturee, convertie en montant au prorata du prix unitaire net
    de la ligne (`subtotal / qty`). Si `qty` est nul (ligne degenerescente),
    aucune part n'a pu etre facturee."""
    if not line.qty:
        return Decimal(0)
    unit_rate = line.subtotal / line.qty
    return (unit_rate * line.qty_invoiced).quantize(Decimal("0.0001"))


def _amount_to_qty_equivalent(line: SalesOrderLine, amount: Decimal) -> Decimal:
    """Inverse de `_already_invoiced_amount` : convertit un montant
    nouvellement facture en increment de `qty_invoiced`."""
    if not line.subtotal:
        return Decimal(0)
    return (amount * line.qty / line.subtotal).quantize(Decimal("0.0001"))


def invoiceable_amount_for_line(line: SalesOrderLine) -> Decimal:
    """Calcule la part actuellement facturable de `line`, selon
    `billing_policy` — toujours idempotent (ne recompte jamais ce qui est
    deja reflete par `qty_invoiced`), jamais negatif.

    - `on_ordered_qty` : la totalite de `subtotal`, une seule fois.
    - `on_delivered_qty` : au prorata de `qty_delivered` vs `qty`.
    - `on_deposit` : facturation en deux temps (RG-SAL-2). Tant qu'aucune
      part n'a encore ete facturee, seule la part `deposit_pct` de
      `subtotal` est facturable (la "facture d'acompte" du CDC). Une fois
      cet acompte facture, plus rien n'est facturable tant que la ligne
      n'est pas livree (`qty_delivered >= qty`) ; a ce moment, le solde
      restant devient facturable en une fois (la "facture finale" a
      laquelle l'acompte est repute impute, cf. simplification assumee en
      tete de module — pas de lettrage `AccMove` reel construit ici).
    - `on_production_progress` (SAL-AVCT1) : au prorata de la quantite
      produite (`mrp.services.public.get_order_produced_qty`) vs `qty`.
      Retourne toujours 0 si `mrp_order_id` est nul (ligne non qualifiee
      "a produire" avec un `MrpOrder` reel — jamais les branches stubees
      de RG-SAL-3)."""
    already = _already_invoiced_amount(line)

    if line.billing_policy == SalesOrderLine.BILLING_ON_ORDERED_QTY:
        target = line.subtotal
    elif line.billing_policy == SalesOrderLine.BILLING_ON_DELIVERED_QTY:
        if not line.qty:
            target = Decimal(0)
        else:
            target = (line.subtotal * line.qty_delivered / line.qty).quantize(Decimal("0.0001"))
    elif line.billing_policy == SalesOrderLine.BILLING_ON_DEPOSIT:
        deposit_pct = line.deposit_pct or Decimal(0)
        deposit_amount = (line.subtotal * deposit_pct / Decimal(100)).quantize(Decimal("0.0001"))
        if already <= 0:
            target = deposit_amount
        elif line.qty and line.qty_delivered >= line.qty:
            target = line.subtotal
        else:
            # Acompte deja facture, ligne pas encore livree : rien de
            # plus a facturer pour l'instant.
            target = already
    elif line.billing_policy == SalesOrderLine.BILLING_ON_PRODUCTION_PROGRESS:
        if line.mrp_order_id is None or not line.qty:
            target = already
        else:
            produced_qty = get_order_produced_qty(line.mrp_order_id) or Decimal(0)
            target = (line.subtotal * produced_qty / line.qty).quantize(Decimal("0.0001"))
    else:  # pragma: no cover - garde defensive, choix FSM-like exhaustifs
        target = already

    invoiceable = target - already
    return invoiceable if invoiceable > 0 else Decimal(0)


def invoice_order(
    order: SalesOrder, user: User, *, lines: list[SalesOrderLine] | None = None
) -> UUID | None:
    """Facture (partiellement ou totalement) `order`, RG-SAL-2. Ne traite
    que `lines` si fourni (facturation partielle explicite), toutes les
    lignes de la commande sinon.

    Si `accounting.services.public.create_customer_invoice_from_source`
    retourne `None` (configuration comptable manquante cote tenant :
    aucun journal de vente, aucune periode ouverte, aucun compte de
    creance/produit) : aucune mutation n'est faite (ni `SalesOrder`, ni
    `SalesOrderLine`), l'etat de la commande ne change pas, et cette
    fonction retourne `None` — jamais une exception. L'appelant (API)
    doit traduire ce `None` en "configuration comptable manquante", pas
    en succes silencieux.

    Si une facture reelle est creee : met a jour `invoiced_amount_mga`
    (cumul) et `qty_invoiced` par ligne, puis transitionne la commande
    vers `invoiced` (`mark_invoiced`) si elle est `delivered` et que le
    cumul couvre desormais `amount_total_mga` (tolerance
    `_FULLY_INVOICED_TOLERANCE_MGA`) — une commande partiellement facturee
    reste dans son etat courant (typiquement `delivered`)."""
    target_lines = list(lines) if lines is not None else list(order.lines.all())

    line_amounts: list[tuple[SalesOrderLine, Decimal]] = [
        (line, invoiceable_amount_for_line(line)) for line in target_lines
    ]
    income_lines: list[dict[str, Any]] = [
        {"account_id": None, "amount": amount, "label": line.description}
        for line, amount in line_amounts
        if amount > 0
    ]
    total = sum((amount for _line, amount in line_amounts if amount > 0), Decimal(0))

    if not income_lines or total <= 0:
        # Rien de facturable actuellement (toutes les lignes deja a jour
        # de leur politique, ou aucune quantite livree/produite) — pas
        # une erreur, simplement rien a faire.
        return None

    move_id = create_customer_invoice_from_source(
        tenant=order.tenant,
        partner_id=order.partner_id,
        date=timezone.now().date(),
        income_lines=income_lines,
        currency=order.currency,
    )
    if move_id is None:
        return None

    for line, amount in line_amounts:
        if amount <= 0:
            continue
        line.qty_invoiced = line.qty_invoiced + _amount_to_qty_equivalent(line, amount)
        line.save(update_fields=["qty_invoiced"])

    order.invoiced_amount_mga = order.invoiced_amount_mga + total

    fully_invoiced = (
        order.amount_total_mga - order.invoiced_amount_mga
    ) <= _FULLY_INVOICED_TOLERANCE_MGA
    if fully_invoiced and order.state == SalesOrder.STATE_DELIVERED:
        attempt_transition(order, "mark_invoiced", user)

    # `state` est toujours inclus (meme s'il n'a pas change quand la
    # commande n'est pas encore entierement facturee) : garde-fou
    # `tests/architecture/test_attempt_transition_saves_state.py` exige un
    # `update_fields` litteral incluant le champ FSM dans la meme
    # fonction que l'appel `attempt_transition()`.
    order.save(update_fields=["invoiced_amount_mga", "state"])

    # SAL-NOTIF1 (§5.5.9, S7) : "a la facturation" — uniquement quand une
    # facture reelle a bien ete creee (jamais sur le `return None`
    # ci-dessus). Meme portee assumee que `services.orders._notify_
    # salesperson` (notifie le commercial, pas directement le client
    # final — cf. sa docstring) ; silencieux si aucun commercial n'est
    # assigne a la commande.
    if order.salesperson is not None:
        message = _("La commande %(reference)s a ete facturee.") % {"reference": order.reference}
        dispatch_notification(
            user=order.salesperson,
            notification_type="sales.order_invoiced",
            payload={
                "order_id": str(order.id),
                "reference": order.reference,
                "invoice_id": str(move_id),
                "message": str(message),
            },
            tenant_id=str(order.tenant_id),
        )
    return move_id
