"""Ecrans HTMX minimaux du module `mrp` (U1) : liste des ordres de
fabrication, detail avec bandeau de workflow (boutons de transition) +
composants planifies/consommes, formulaire de creation. Meme patron que
`apps.accounting.views`."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import cast
from uuid import UUID

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.catalog.services.public import get_variant_sector_code
from apps.core.models.user import User
from apps.core.services.workflow import TransitionPermissionError
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.mrp.models import (
    MrpBom,
    MrpCra,
    MrpCri,
    MrpOrder,
    MrpOrderComponent,
    MrpSubcontractOrder,
    MrpWorkcenter,
    MrpWorkOrder,
    MrpWorkshop,
)
from apps.mrp.services import procurement
from apps.mrp.services.cra import create_cra, reject_cra, submit_cra, validate_cra
from apps.mrp.services.interventions import close_cri, create_cri, declare_scrap
from apps.mrp.services.orders import (
    advance_work_order,
    cancel_order,
    close_order,
    confirm_order,
    create_order,
    create_work_order,
    done_work_order,
    pause_work_order,
    receive_from_subcontractor,
    reserve_order,
    resume_order,
    send_to_quality_control,
    send_to_subcontractor,
    start_order,
    start_work_order,
    suspend_order,
)
from apps.mrp.services.procurement import get_or_create_procurement_state
from apps.mrp.services.quality import first_pass_yield
from apps.mrp.services.transformation import (
    available_output_locations,
    finish_transformation_order,
    order_genealogy,
    order_yield,
    record_component_consumption,
)

COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="state", label="Statut"),
    Column(key="qty", label="Quantite", searchable=False),
]

_ACTIONS = {
    "confirm": lambda order, user, _post: confirm_order(order, user),
    "reserve": lambda order, user, _post: reserve_order(order, user),
    "start": lambda order, user, _post: start_order(order, user),
    "suspend": lambda order, user, post: suspend_order(order, user, reason=post.get("reason", "")),
    "resume": lambda order, user, _post: resume_order(order, user),
    "send_to_quality_control": lambda order, user, _post: send_to_quality_control(order, user),
    "finish": lambda order, user, post: finish_transformation_order(
        order,
        user,
        qty_produced=Decimal(post.get("qty_produced") or "0"),
        qty_scrapped=Decimal(post.get("qty_scrapped") or "0"),
        output_lot_name=post.get("output_lot_name", ""),
        location_to_id=post.get("location_to_id") or None,
    ),
    "close": lambda order, user, _post: close_order(order, user),
    "cancel": lambda order, user, post: cancel_order(order, user, reason=post.get("reason", "")),
}

# MrpBomLineState (MRP-FSM1) : suivi d'approvisionnement PAR COMPOSANT
# d'ordre (order_component = OneToOneField(MrpOrderComponent)), independant
# de `MrpOrder.state` — boutons places sur la ligne du composant concerne
# dans le tableau des composants planifies.
_PROCUREMENT_ACTIONS = {
    "request_sample": procurement.request_sample,
    "evaluate_sample": procurement.evaluate_sample,
    "validate_supplier": procurement.validate_supplier,
    "place_order": procurement.order,
    "receive_component": procurement.receive,
    "declare_shortage": procurement.declare_shortage,
    "quality_control_component": procurement.send_to_quality_control,
    "approve_component": procurement.approve,
    "reject_component": procurement.reject,
    "start_production_component": procurement.start_production,
    "consume_component": procurement.consume,
}


@login_required
def order_list(request: HttpRequest) -> HttpResponse:
    queryset = MrpOrder.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="mrp.orders",
        columns=COLUMNS,
        queryset=queryset,
        page_template="mrp/list.html",
        page_context={"row_url_name": "mrp:detail"},
    )


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


@login_required
def order_detail(request: HttpRequest, order_id: str) -> HttpResponse:
    order = get_object_or_404(MrpOrder, id=order_id)
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            handler = _ACTIONS.get(action)
            if handler is not None:
                handler(order, user, post)
            elif action == "create_work_order":
                workcenter = get_object_or_404(MrpWorkcenter, id=post.get("workcenter_id"))
                create_work_order(
                    order,
                    workcenter=workcenter,
                    qty_planned=Decimal(post.get("wo_qty_planned") or "0"),
                    sequence=int(post.get("wo_sequence") or "0"),
                    duration_planned_min=int(post.get("wo_duration_planned_min") or "0"),
                )
            elif action == "start_work_order":
                work_order = get_object_or_404(
                    MrpWorkOrder, id=post.get("work_order_id"), order=order
                )
                start_work_order(work_order, operator=user)
            elif action == "pause_work_order":
                work_order = get_object_or_404(
                    MrpWorkOrder, id=post.get("work_order_id"), order=order
                )
                pause_work_order(work_order)
            elif action == "done_work_order":
                work_order = get_object_or_404(
                    MrpWorkOrder, id=post.get("work_order_id"), order=order
                )
                done_work_order(
                    work_order,
                    qty_done=Decimal(post.get("wo_qty_done") or "0"),
                    qty_rejected=Decimal(post.get("wo_qty_rejected") or "0"),
                )
            elif action == "create_subcontract":
                send_to_subcontractor(
                    order,
                    partner_id=UUID(post.get("partner_id") or ""),
                    variant_id=UUID(post.get("sub_variant_id") or ""),
                    qty=Decimal(post.get("sub_qty") or "0"),
                    price_unit=Decimal(post.get("price_unit") or "0"),
                )
            elif action == "receive_subcontract":
                subcontract_order = get_object_or_404(
                    MrpSubcontractOrder, id=post.get("subcontract_id"), order=order
                )
                receive_from_subcontractor(
                    subcontract_order,
                    qty_received=Decimal(post.get("sub_qty_received") or "0"),
                    qty_rejected=Decimal(post.get("sub_qty_rejected") or "0"),
                )
            elif action == "create_cra":
                workshop = get_object_or_404(MrpWorkshop, id=post.get("cra_workshop_id"))
                create_cra(
                    tenant=tenant,
                    employee=user,
                    workshop=workshop,
                    date=parse_date(post.get("cra_date", "")) or timezone.now().date(),
                    hours=Decimal(post.get("cra_hours") or "0"),
                    order=order,
                    qty_done=Decimal(post.get("cra_qty_done") or "0"),
                    activity_type=post.get("cra_activity_type", ""),
                    comment=post.get("cra_comment", ""),
                )
            elif action == "submit_cra":
                cra = get_object_or_404(MrpCra, id=post.get("cra_id"), order=order)
                submit_cra(cra, user)
            elif action == "validate_cra":
                cra = get_object_or_404(MrpCra, id=post.get("cra_id"), order=order)
                validate_cra(cra, user)
            elif action == "reject_cra":
                cra = get_object_or_404(MrpCra, id=post.get("cra_id"), order=order)
                reject_cra(cra, user)
            elif action == "create_cri":
                workcenter = get_object_or_404(MrpWorkcenter, id=post.get("cri_workcenter_id"))
                create_cri(
                    tenant=tenant,
                    type=post.get("cri_type", ""),
                    workcenter=workcenter,
                    date=parse_date(post.get("cri_date", "")) or timezone.now().date(),
                    order=order,
                    intervenant_user=user,
                    duration_min=int(post.get("cri_duration_min") or "0"),
                    description=post.get("cri_description", ""),
                    downtime_min=int(post.get("cri_downtime_min") or "0"),
                )
            elif action == "close_cri":
                cri = get_object_or_404(MrpCri, id=post.get("cri_id"), order=order)
                close_cri(cri)
            elif action == "create_scrap":
                declare_scrap(
                    order,
                    declared_by=user,
                    qty=Decimal(post.get("scrap_qty") or "0"),
                    reason=post.get("scrap_reason", ""),
                )
            elif action == "record_component_consumption":
                component = get_object_or_404(
                    MrpOrderComponent, id=post.get("component_id"), order=order
                )
                record_component_consumption(
                    component,
                    lot_name=post.get("consumption_lot", ""),
                    qty_consumed=Decimal(post.get("consumption_qty") or "0"),
                )
            elif action in _PROCUREMENT_ACTIONS:
                component = get_object_or_404(
                    MrpOrderComponent, id=post.get("component_id"), order=order
                )
                state = get_or_create_procurement_state(component)
                _PROCUREMENT_ACTIONS[action](state, user)
        except (ValidationError, InvalidOperation, ValueError, TransitionPermissionError) as exc:
            error = _error_message(exc)
        else:
            return redirect("mrp:detail", order_id=order.id)

    return render(
        request,
        "mrp/detail.html",
        {
            "order": order,
            "components": order.components.select_related("procurement_state").all(),
            "work_orders": order.work_orders.select_related("workcenter").all(),
            "workcenters": MrpWorkcenter.objects.filter(tenant=tenant, is_active=True),
            "subcontract_orders": order.subcontract_orders.all(),
            "cra_entries": order.cra_entries.select_related("employee").all(),
            "workshops": MrpWorkshop.objects.filter(tenant=tenant, is_active=True),
            "cri_entries": order.cri_entries.all(),
            "scraps": order.scraps.all(),
            "error": error,
            "yield_data": order_yield(order),
            "genealogy": order_genealogy(order),
            "output_locations": available_output_locations(order),
            "first_pass_yield": first_pass_yield(order),
            # Bloc C, C5 (PRD-4) : nudge écran — rend `output_lot_name`
            # obligatoire par défaut pour un ordre sur un produit
            # agroalimentaire (jamais un blocage service, cf.
            # `services/transformation.py`).
            "variant_sector_code": (
                get_variant_sector_code(order.variant_id) if order.variant_id else None
            ),
            # Chatter (Sprint 3 / L2) : premiere utilisation dans `mrp`,
            # meme patron que `apps.sales.views` (cf. templates/cotton/
            # chatter.html) — un seul fil par ordre de fabrication,
            # alimente automatiquement par `advance_work_order` (T2) a
            # chaque changement d'etape kanban.
            "chatter_app_label": order._meta.app_label,
            "chatter_model": order._meta.model_name,
            "chatter_object_id": str(order.id),
        },
    )


@login_required
def order_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    boms = MrpBom.objects.filter(tenant=tenant, state=MrpBom.STATE_ACTIVE).order_by("code")
    workshops = MrpWorkshop.objects.filter(tenant=tenant, is_active=True).order_by("code")
    default_bom = boms.first()
    default_workshop = workshops.first()
    error = None

    if request.method == "POST":
        try:
            bom = get_object_or_404(MrpBom, id=request.POST.get("bom_id"))
            workshop = get_object_or_404(MrpWorkshop, id=request.POST.get("workshop_id"))
            order = create_order(
                tenant=tenant,
                bom=bom,
                workshop=workshop,
                qty=Decimal(request.POST.get("qty") or "1"),
            )
        except (InvalidOperation, ValidationError) as exc:
            error = str(exc)
        else:
            return redirect("mrp:detail", order_id=order.id)

    return render(
        request,
        "mrp/create.html",
        {
            "boms": boms,
            "workshops": workshops,
            "default_bom_id": default_bom.id if default_bom else None,
            "default_workshop_id": default_workshop.id if default_workshop else None,
            "error": error,
        },
    )


@login_required
def work_order_kanban(request: HttpRequest) -> HttpResponse:
    """T2 (L3 Textile, cf. docs/planning/2026-refonte-ux-sprints.md §5) :
    tableau atelier — une colonne par type de poste de charge
    (`MrpWorkcenter.TYPE_CHOICES` couvre déjà coupe/couture/broderie/
    impression/finition/contrôle/emballage, aucun nouveau champ), une
    carte par ordre de travail non terminé. "Déplacer une carte" se fait
    par bouton (jamais de glisser-déposer — cohérent avec l'unique autre
    kanban du dépôt, `apps.projects`, lui aussi sans drag-and-drop) :
    `advance_work_order` termine l'étape, démarre la suivante si elle
    existe et journalise dans le chatter de l'ordre."""
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        try:
            work_order = get_object_or_404(
                MrpWorkOrder, id=request.POST.get("work_order_id"), tenant=tenant
            )
            advance_work_order(
                work_order,
                user,
                qty_done=Decimal(request.POST.get("qty_done") or "0"),
                qty_rejected=Decimal(request.POST.get("qty_rejected") or "0"),
            )
        except (ValidationError, InvalidOperation) as exc:
            error = str(exc)
        else:
            return redirect("mrp:kanban")

    work_orders = (
        MrpWorkOrder.objects.filter(tenant=tenant, is_active=True)
        .exclude(state=MrpWorkOrder.STATE_DONE)
        .select_related("workcenter", "order")
        .order_by("sequence")
    )
    fpy_by_order: dict[UUID, Decimal] = {}
    cards_by_type: dict[str, list[MrpWorkOrder]] = {}
    for work_order in work_orders:
        if work_order.order_id not in fpy_by_order:
            fpy_by_order[work_order.order_id] = first_pass_yield(work_order.order)
        work_order.fpy = fpy_by_order[work_order.order_id]  # type: ignore[attr-defined]
        cards_by_type.setdefault(work_order.workcenter.type, []).append(work_order)

    columns = [
        (code, label, cards_by_type.get(code, [])) for code, label in MrpWorkcenter.TYPE_CHOICES
    ]

    return render(
        request,
        "mrp/kanban.html",
        {"columns": columns, "error": error},
    )
