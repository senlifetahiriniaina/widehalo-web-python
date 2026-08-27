"""Ecrans HTMX minimaux du module `mrp` (U1) : liste des ordres de
fabrication, detail avec bandeau de workflow (boutons de transition) +
composants planifies/consommes, formulaire de creation. Meme patron que
`apps.accounting.views`."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models.user import User
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.mrp.models import MrpBom, MrpOrder, MrpWorkshop
from apps.mrp.services.orders import (
    cancel_order,
    close_order,
    confirm_order,
    create_order,
    finish_order,
    reserve_order,
    resume_order,
    send_to_quality_control,
    start_order,
    suspend_order,
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
    "finish": lambda order, user, post: finish_order(
        order, user, qty_produced=Decimal(post.get("qty_produced") or "0")
    ),
    "close": lambda order, user, _post: close_order(order, user),
    "cancel": lambda order, user, post: cancel_order(order, user, reason=post.get("reason", "")),
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


@login_required
def order_detail(request: HttpRequest, order_id: str) -> HttpResponse:
    order = get_object_or_404(MrpOrder, id=order_id)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        handler = _ACTIONS.get(action)
        if handler is not None:
            try:
                handler(order, user, request.POST)
            except (ValidationError, InvalidOperation) as exc:
                error = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            else:
                return redirect("mrp:detail", order_id=order.id)

    return render(
        request,
        "mrp/detail.html",
        {"order": order, "components": order.components.all(), "error": error},
    )


@login_required
def order_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    boms = MrpBom.objects.filter(tenant=tenant, state=MrpBom.STATE_ACTIVE)
    workshops = MrpWorkshop.objects.filter(tenant=tenant, is_active=True)
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
        request, "mrp/create.html", {"boms": boms, "workshops": workshops, "error": error}
    )
