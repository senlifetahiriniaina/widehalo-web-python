"""Ordres de fabrication et ordres de travail (§5.3.4, RG-MRP-7/8) :
workflow complet reutilisant `django-fsm-2`/`attempt_transition()` du
socle (meme patron que `AccMove.invoice_state`), multi-ateliers et
sous-traitance."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.chatter import post_message
from apps.core.services.sequences import next_reference
from apps.core.services.workflow import attempt_transition
from apps.mrp.models import (
    MrpBom,
    MrpOperation,
    MrpOrder,
    MrpOrderComponent,
    MrpRoutingStep,
    MrpSubcontractOrder,
    MrpWorkcenter,
    MrpWorkOrder,
    MrpWorkshop,
)
from apps.mrp.services.bom import explode


def create_order(
    *,
    tenant: Tenant,
    bom: MrpBom,
    workshop: MrpWorkshop,
    qty: Decimal,
    variant_id: UUID | None = None,
    uom_code: str = "",
    priority: str = MrpOrder.PRIORITY_NORMAL,
) -> MrpOrder:
    reference = next_reference(tenant, "MRP-OF", timezone.now().year)
    return MrpOrder.objects.create(
        tenant=tenant,
        reference=reference,
        bom=bom,
        routing=bom.routing,
        workshop=workshop,
        variant_id=variant_id,
        qty=qty,
        uom_code=uom_code or bom.uom_code,
        priority=priority,
    )


def confirm_order(order: MrpOrder, user: User) -> MrpOrder:
    """Confirme l'ordre puis materialise les composants planifies
    (RG-MRP-2/3/4) via l'eclatement de la nomenclature."""
    attempt_transition(order, "confirm", user)
    order.save(update_fields=["state"])

    for row in explode(order.bom, order.qty):
        MrpOrderComponent.objects.create(
            tenant=order.tenant,
            order=order,
            bom_line_id=row["bom_line_id"],
            variant_id=row["component_variant_id"],
            qty_planned=row["qty"],
            uom_code=row["uom_code"],
        )
    return order


def reserve_order(order: MrpOrder, user: User) -> MrpOrder:
    """Bloc C, C1 : réservation RÉELLE (`stocks.services.public.
    check_and_reserve_stock`), plus le simple marquage `state="reserved"`
    d'avant ce chantier. Trois états distincts, jamais confondus :
    `"reserved"` (réservation réelle obtenue), `"insufficient_stock"`
    (variant résolu mais aucun quant unique ne couvre `qty_planned` — un
    vrai gap physique que l'utilisateur qui réserve POUR PRODUIRE doit
    voir), `"planned"` inchangé (aucun `variant_id` — gap de
    configuration BOM/catalogue, structurellement différent d'un gap de
    stock — la fixture `order_setup` existante produit ce cas après
    `confirm_order`, jamais une exception ici).

    La transition FSM vers `STATE_RESERVED` n'est JAMAIS bloquée par
    l'échec de réservation d'un seul composant — même discipline "jamais
    un blocage silencieux qui masque le problème" que le reste du dépôt
    (ex. `validate_inventory`). Le gap reste visible via
    `component.state` sur le tableau des composants déjà affiché par
    `detail.html`."""
    # Import local (pas au niveau module) : `apps.mrp.apps.ready()`
    # importe `services.public` -> `services.orders` au demarrage de
    # Django (`ai_context_registration`), AVANT que le registre
    # d'applications soit completement peuple — un import de niveau
    # module de `stocks.services.public` a ce stade declenche une
    # dependance circulaire reelle et preexistante
    # (stocks.public -> stocks.pickings -> stocks.moves ->
    # accounting.public -> accounting.landed_costs -> stocks.public,
    # `ImportError: cannot import name ... from partially initialized
    # module`) qui ne se manifeste que via CE chemin d'import precoce.
    # Reporter l'import a l'appel (bien apres que toutes les apps soient
    # `ready()`) contourne le probleme sans toucher au graphe existant.
    from apps.stocks.services.public import check_and_reserve_stock

    attempt_transition(order, "reserve", user)
    order.save(update_fields=["state"])
    today = timezone.now().date()
    for component in order.components.all():
        if component.variant_id is None:
            continue
        reservation_id = check_and_reserve_stock(
            order.tenant,
            variant_id=component.variant_id,
            qty=component.qty_planned,
            date=today,
            source_object=component,
        )
        if reservation_id is not None:
            component.state = "reserved"
            component.reservation_id = reservation_id
            component.save(update_fields=["state", "reservation_id"])
        else:
            component.state = "insufficient_stock"
            component.save(update_fields=["state"])
    return order


def _release_component_reservations(order: MrpOrder) -> None:
    """Bloc C, C1 : libère toute réservation de composant encore active à
    la clôture/annulation de l'ordre — évite de laisser une réservation
    "dangling" indéfiniment une fois la ressource réelle introduite par
    ce chantier. `release_stock_reservation` est idempotente (jamais une
    exception), donc sûre même sur un composant déjà libéré."""
    from apps.stocks.services.public import release_stock_reservation

    for component in order.components.exclude(reservation_id=None):
        if component.reservation_id is None:
            continue
        released = release_stock_reservation(
            order.tenant,
            reservation_id=component.reservation_id,
            reason=_("Clôture/annulation de l'ordre de fabrication."),
        )
        if released:
            component.reservation_id = None
            component.save(update_fields=["reservation_id"])


def start_order(order: MrpOrder, user: User) -> MrpOrder:
    attempt_transition(order, "start", user)
    order.date_start = timezone.now()
    order.save(update_fields=["state", "date_start"])
    return order


def suspend_order(order: MrpOrder, user: User, *, reason: str) -> MrpOrder:
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour suspendre un ordre de fabrication."))
    attempt_transition(order, "suspend", user, comment=reason)
    order.suspend_reason = reason
    order.save(update_fields=["state", "suspend_reason"])
    return order


def resume_order(order: MrpOrder, user: User) -> MrpOrder:
    attempt_transition(order, "resume", user)
    order.save(update_fields=["state"])
    return order


def send_to_quality_control(order: MrpOrder, user: User) -> MrpOrder:
    attempt_transition(order, "send_to_quality_control", user)
    order.save(update_fields=["state"])
    return order


def finish_order(
    order: MrpOrder, user: User, *, qty_produced: Decimal, qty_scrapped: Decimal = Decimal(0)
) -> MrpOrder:
    attempt_transition(order, "finish", user)
    order.qty_produced = qty_produced
    order.qty_scrapped = qty_scrapped
    order.date_end = timezone.now()
    order.save(update_fields=["state", "qty_produced", "qty_scrapped", "date_end"])
    return order


def close_order(order: MrpOrder, user: User) -> MrpOrder:
    attempt_transition(order, "close", user)
    order.save(update_fields=["state"])
    _release_component_reservations(order)
    return order


def cancel_order(order: MrpOrder, user: User, *, reason: str) -> MrpOrder:
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour annuler un ordre de fabrication."))
    attempt_transition(order, "cancel", user, comment=reason)
    order.cancel_reason = reason
    order.save(update_fields=["state", "cancel_reason"])
    # Bloc C, C1 : par cohérence/futur-proofing — `cancel` n'est
    # aujourd'hui atteignable qu'avant `reserve` (source=[DRAFT,
    # CONFIRMED]), donc jamais un chemin réellement vivant pour une
    # réservation active, mais gardé cohérent avec `close_order` : c'est
    # ce chantier qui introduit la ressource réelle, donc c'est lui qui
    # doit éviter de la laisser "dangling".
    _release_component_reservations(order)
    return order


def create_work_order(
    order: MrpOrder,
    *,
    workcenter: MrpWorkcenter,
    qty_planned: Decimal,
    sequence: int = 0,
    routing_step: MrpRoutingStep | None = None,
    duration_planned_min: int = 0,
) -> MrpWorkOrder:
    return MrpWorkOrder.objects.create(
        tenant=order.tenant,
        order=order,
        routing_step=routing_step,
        workcenter=workcenter,
        sequence=sequence,
        qty_planned=qty_planned,
        duration_planned_min=duration_planned_min,
    )


def start_work_order(work_order: MrpWorkOrder, *, operator: User | None = None) -> MrpWorkOrder:
    work_order.state = MrpWorkOrder.STATE_IN_PROGRESS
    work_order.date_start = timezone.now()
    work_order.operator = operator
    work_order.save(update_fields=["state", "date_start", "operator"])
    return work_order


def pause_work_order(work_order: MrpWorkOrder) -> MrpWorkOrder:
    work_order.state = MrpWorkOrder.STATE_PAUSED
    work_order.save(update_fields=["state"])
    return work_order


def done_work_order(
    work_order: MrpWorkOrder, *, qty_done: Decimal, qty_rejected: Decimal = Decimal(0)
) -> MrpWorkOrder:
    now = timezone.now()
    duration_real_min = 0
    if work_order.date_start is not None:
        duration_real_min = int((now - work_order.date_start).total_seconds() // 60)

    work_order.state = MrpWorkOrder.STATE_DONE
    work_order.qty_done = qty_done
    work_order.qty_rejected = qty_rejected
    work_order.date_end = now
    work_order.duration_real_min = duration_real_min
    work_order.save(
        update_fields=["state", "qty_done", "qty_rejected", "date_end", "duration_real_min"]
    )
    return work_order


def advance_work_order(
    work_order: MrpWorkOrder,
    user: User,
    *,
    qty_done: Decimal,
    qty_rejected: Decimal = Decimal(0),
) -> MrpWorkOrder:
    """T2 (L3 Textile, cf. docs/planning/2026-refonte-ux-sprints.md §5) :
    "déplacer une carte [du kanban atelier] change l'état et journalise
    dans le chatter" — termine `work_order` (`done_work_order`, inchangé),
    démarre automatiquement le prochain ordre de travail EN ATTENTE de la
    même gamme (`sequence` strictement supérieure, le plus proche) s'il en
    existe un, et journalise la transition d'étape sur le fil de
    discussion de l'ORDRE (pas de l'ordre de travail lui-même — un seul
    fil par ordre de fabrication, cohérent avec le seul autre usage du
    chatter à ce jour, `sales.SalesOrder`).

    Ne démarre jamais automatiquement un ordre de travail qui n'est pas
    `pending` (ex. déjà en pause par un opérateur) — l'automatisation ne
    doit jamais écraser une décision humaine explicite."""
    order = work_order.order
    workcenter_label = work_order.workcenter.get_type_display()
    work_order = done_work_order(work_order, qty_done=qty_done, qty_rejected=qty_rejected)

    next_work_order = (
        order.work_orders.filter(state=MrpWorkOrder.STATE_PENDING, sequence__gt=work_order.sequence)
        .order_by("sequence")
        .first()
    )
    if next_work_order is not None:
        start_work_order(next_work_order, operator=user)
        next_label = next_work_order.workcenter.get_type_display()
        note = _("Étape %(from)s terminée (%(done)s bonnes, %(rejected)s rejetées) → %(to)s.") % {
            "from": workcenter_label,
            "done": qty_done,
            "rejected": qty_rejected,
            "to": next_label,
        }
    else:
        note = _(
            "Étape %(from)s terminée (%(done)s bonnes, %(rejected)s rejetées) — "
            "fin de gamme, aucune étape suivante en attente."
        ) % {"from": workcenter_label, "done": qty_done, "rejected": qty_rejected}

    post_message(order, author=user, body=note, is_note=True)
    return work_order


def send_to_subcontractor(
    order: MrpOrder,
    *,
    partner_id: UUID,
    variant_id: UUID,
    qty: Decimal,
    price_unit: Decimal = Decimal(0),
    operation: MrpOperation | None = None,
    uom_code: str = "",
    lot_name: str = "",
) -> MrpSubcontractOrder:
    """RG-MRP-8 : trace l'envoi de matiere a un sous-traitant.

    Bloc C, C2 : le mouvement de stock vers l'emplacement virtuel « chez
    le sous-traitant » est desormais un VRAI `StkMove`
    (`stocks.services.public.send_to_subcontractor`), plus une simple
    trace `mrp` sans contrepartie stock. Refuse (`ValidationError`) si
    l'atelier de l'ordre n'a aucun entrepot configure — meme discipline
    que le reste de ce fichier (`suspend_order`/`cancel_order`), un motif
    utilisateur explicite plutot qu'un `None` silencieux, cette action
    etant toujours declenchee par un utilisateur reel depuis l'ecran de
    detail de l'ordre."""
    # Import local : meme raison que `reserve_order` ci-dessus (cycle
    # d'import reel via apps.mrp.apps.ready()).
    from apps.stocks.services.public import (
        send_to_subcontractor as stocks_send_to_subcontractor,
    )

    if order.workshop.warehouse_id is None:
        raise ValidationError(
            _("L'atelier de cet ordre n'a aucun entrepôt configuré pour la sous-traitance.")
        )
    move_id = stocks_send_to_subcontractor(
        tenant=order.tenant,
        variant_id=variant_id,
        qty=qty,
        uom=uom_code or order.uom_code,
        warehouse_id=order.workshop.warehouse_id,
        date=timezone.now().date(),
        source_document=order.reference,
        unit_cost_mga=price_unit,
        lot_name=lot_name,
    )
    return MrpSubcontractOrder.objects.create(
        tenant=order.tenant,
        order=order,
        partner_id=partner_id,
        operation=operation,
        variant_id=variant_id,
        qty=qty,
        price_unit=price_unit,
        date_sent=timezone.now().date(),
        send_move_id=move_id,
    )


def receive_from_subcontractor(
    subcontract_order: MrpSubcontractOrder,
    *,
    qty_received: Decimal,
    qty_rejected: Decimal = Decimal(0),
    rebut_location_id: UUID | None = None,
) -> MrpSubcontractOrder:
    """Bloc C, C2 : reçoit (ou rejette) la matière chez le sous-traitant
    via un VRAI mouvement de stock retour (`stocks.services.public.
    receive_from_subcontractor`), quand `send_move_id` a été renseigné à
    l'envoi. `send_move_id` absent (traces `MrpSubcontractOrder`
    antérieures à ce chantier, ou envoi créé sans passer par
    `send_to_subcontractor` ci-dessus) : repli sur l'ancien comportement
    (trace `mrp` seule, aucun mouvement de stock) — jamais une exception
    pour une donnée historique légitime."""
    if subcontract_order.send_move_id is not None:
        # Import local : meme raison que `reserve_order` ci-dessus.
        from apps.stocks.services.public import (
            receive_from_subcontractor as stocks_receive_from_subcontractor,
        )

        stocks_receive_from_subcontractor(
            tenant=subcontract_order.tenant,
            send_move_id=subcontract_order.send_move_id,
            date=timezone.now().date(),
            qty_received=qty_received,
            qty_rejected=qty_rejected,
            rebut_location_id=rebut_location_id,
        )
    subcontract_order.state = MrpSubcontractOrder.STATE_RECEIVED
    subcontract_order.qty_received = qty_received
    subcontract_order.qty_rejected = qty_rejected
    subcontract_order.date_received = timezone.now().date()
    subcontract_order.save(update_fields=["state", "qty_received", "qty_rejected", "date_received"])
    return subcontract_order
