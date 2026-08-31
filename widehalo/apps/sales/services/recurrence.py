"""Planification periodique (§5.5.3, S5, RG-SAL-6) : « Une commande peut
etre modelisee comme recurrente : le systeme genere automatiquement une
nouvelle commande a l'echeance, a partir d'un gabarit, et notifie le
commercial pour validation. La generation n'est JAMAIS automatiquement
confirmee. »

`generate_due_order` est le coeur de la regle : elle cree une nouvelle
`SalesOrder` en `draft` (jamais `confirmed`) a partir du gabarit
`SalesRecurrence.template_order`, avance `next_run`, et notifie le
commercial via `apps.core.services.notifications.dispatch_notification`
(reutilisation du canal generique du socle, Lot 1 etape 11 — aucune
nouvelle infrastructure de notification n'est creee ici).

`run_due_recurrences` boucle sur les recurrences actives et arrivees a
echeance d'un tenant. Le declenchement periodique reel (cron/planification
Django-Q2) est hors-perimetre de ce lot (cf. plan, sous-sequencement S5) :
aucun mecanisme de planification de type cron n'existe encore ailleurs
dans le projet (`apps.core.tasks.enqueue` n'est utilise que pour des
taches ponctuelles declenchees par un evenement, jamais pour une
planification recurrente) — inventer un ordonnanceur cron complet pour ce
seul lot serait hors-scope. Le choix retenu, le plus simple qui reste
correct : `run_due_recurrences` est un simple callable synchrone (meme
patron que tous les services `sales` existants), invoque directement -
sans passer par `enqueue` - par la commande de management
`run_sales_recurrences` (cf. `apps/sales/management/commands/`), destinee
a etre appelee quotidiennement par une tache ops externe (cron systeme ou,
plus tard, une entree de planification Django-Q2 — cette derniere n'est
pas cablee automatiquement dans ce lot, cf. plan)."""

from __future__ import annotations

import datetime as dt

from dateutil.relativedelta import relativedelta
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.notifications import dispatch_notification
from apps.core.services.sequences import next_reference
from apps.sales.models import SalesOrder, SalesOrderLine, SalesRecurrence

_INTERVAL_STEPS: dict[str, relativedelta] = {
    SalesRecurrence.INTERVAL_WEEKLY: relativedelta(days=7),
    SalesRecurrence.INTERVAL_MONTHLY: relativedelta(months=1),
    SalesRecurrence.INTERVAL_QUARTERLY: relativedelta(months=3),
    SalesRecurrence.INTERVAL_YEARLY: relativedelta(years=1),
}


def create_recurrence(
    *,
    tenant: Tenant,
    name: str,
    interval: str,
    start_date: dt.date,
    template_order: SalesOrder,
    day_rule: str = "",
    end_date: dt.date | None = None,
) -> SalesRecurrence:
    """`next_run` demarre a `start_date` : la premiere generation possible
    est donc a partir de cette date (jamais avant)."""
    return SalesRecurrence.objects.create(
        tenant=tenant,
        name=name,
        interval=interval,
        day_rule=day_rule,
        start_date=start_date,
        end_date=end_date,
        next_run=start_date,
        template_order=template_order,
    )


def _next_occurrence(current: dt.date, interval: str) -> dt.date:
    return current + _INTERVAL_STEPS[interval]


def generate_due_order(recurrence: SalesRecurrence, user: User) -> SalesOrder | None:
    """RG-SAL-6 : genere la commande a echeance a partir du gabarit, sans
    jamais la confirmer automatiquement. Retourne `None` (jamais une
    exception) quand rien n'est a generer : recurrence inactive, pas
    encore a echeance, ou echue (`end_date` depassee) — ce sont des cas
    normaux, pas des erreurs."""
    today = timezone.now().date()
    if not recurrence.is_active:
        return None
    if recurrence.next_run > today:
        return None
    if recurrence.end_date is not None and today > recurrence.end_date:
        return None

    template = recurrence.template_order
    reference = next_reference(recurrence.tenant, "CMD", timezone.now().year)
    new_order = SalesOrder.objects.create(
        tenant=recurrence.tenant,
        reference=reference,
        partner_id=template.partner_id,
        contact=template.contact,
        source_lead_id=template.source_lead_id,
        date=today,
        pricelist_id=template.pricelist_id,
        currency=template.currency,
        payment_term_id=template.payment_term_id,
        incoterm=template.incoterm,
        delivery_address=template.delivery_address,
        salesperson=template.salesperson,
        notes=template.notes,
        internal_notes=template.internal_notes,
        is_recurring=True,
        recurrence_id=recurrence.id,
    )
    for line in template.lines.all():
        SalesOrderLine.objects.create(
            tenant=new_order.tenant,
            order=new_order,
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
            billing_policy=line.billing_policy,
            deposit_pct=line.deposit_pct,
        )
    new_order.amount_untaxed = template.amount_untaxed
    new_order.amount_tax = template.amount_tax
    new_order.amount_total = template.amount_total
    new_order.amount_total_mga = template.amount_total_mga
    new_order.save(
        update_fields=["amount_untaxed", "amount_tax", "amount_total", "amount_total_mga"]
    )

    recurrence.next_run = _next_occurrence(recurrence.next_run, recurrence.interval)
    recurrence.save(update_fields=["next_run"])

    # RG-SAL-6 : "notifie le commercial pour validation" — le commercial
    # rattache au gabarit s'il en a un, sinon l'utilisateur/systeme ayant
    # declenche la generation (ex. la commande de management ops).
    recipient = template.salesperson or user
    dispatch_notification(
        user=recipient,
        notification_type="sales.recurring_order_generated",
        payload={
            "order_id": str(new_order.id),
            "reference": new_order.reference,
            "recurrence_id": str(recurrence.id),
            "message": str(
                _("Une commande récurrente a été générée en brouillon et attend votre validation.")
            ),
        },
        tenant_id=str(recurrence.tenant_id),
    )

    return new_order


def run_due_recurrences(tenant: Tenant, user: User) -> list[SalesOrder]:
    """Genere toutes les commandes a echeance du tenant — appelee par la
    commande de management `run_sales_recurrences` (une fois par tenant
    actif, cf. module docstring pour le choix de declenchement retenu)."""
    today = timezone.now().date()
    recurrences = SalesRecurrence.objects.filter(tenant=tenant, is_active=True, next_run__lte=today)
    generated: list[SalesOrder] = []
    for recurrence in recurrences:
        order = generate_due_order(recurrence, user)
        if order is not None:
            generated.append(order)
    return generated
