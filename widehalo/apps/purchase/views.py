"""Ecrans HTMX minimaux du module `purchase` (PU8, §5.6 — dernier lot de
`purchase`) : demandes d'achat, appels d'offres et commandes d'achat
(liste SmartTable, fiche detail avec bandeau de workflow, formulaire de
creation). Meme patron que `apps.sales.views`/`apps.mrp.views` :
session-authentifie (`@login_required`), appel direct aux `services/*` de
`purchase`, jamais l'API JWT interne.

**CRA/CRI** (comptes rendus d'activite/incident achats) : contrairement au
patron `requisitions`/`rfq`/`orders` (liste + fiche detail dediee + creation
sur 3 pages separees), ces deux entites sont volontairement rendues sur
UNE SEULE page chacune (liste + formulaire de creation + actions de
transition en ligne dans le tableau, jamais de fiche detail dediee) — cf.
`cra_list`/`cri_list` ci-dessous. Deviation documentee et deliberee vis-a-vis
du CDC PU8 (qui suggere "liste + detail + creation" pour ces deux entites,
cf. plan) : le plafond archi T7 `tests/architecture/test_budget.py`
(90 ecrans max, deja a 74/90 avant ce lot) rend impossible de livrer les
~20 gabarits qu'impliquerait un decoupage integral liste/detail/creation
pour 6 entites transactionnelles (demandes, RFQ, commandes, CRA, CRI,
substituts) SANS depasser ce plafond. `PurCra`/`PurCri` ont un cycle de
vie trivial (2-3 champs d'etat, memes transitions triviales que
`PurRequisition`, cf. `models.py`) : une ligne de tableau avec ses boutons
d'action inline porte exactement la meme information qu'une fiche detail
dediee, sans gaspiller un gabarit entier. `requisitions`/`rfq`/`orders`
(bien plus riches — lignes, FSM complete, sous-formulaires) gardent le
decoupage a 3 pages, seul un budget de gabarits nettement plus genereux
justifierait de le faire aussi pour CRA/CRI."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.core.models.user import User
from apps.core.services.workflow import TransitionPermissionError
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.purchase.models import (
    PrcPriceWatchTarget,
    PurCra,
    PurCri,
    PurOrder,
    PurOrderLine,
    PurRequisition,
    PurRfq,
)
from apps.purchase.services.cra import create_cra, reject_cra, submit_cra, validate_cra
from apps.purchase.services.cri import close_cri, create_cri
from apps.purchase.services.invoicing import record_supplier_invoice
from apps.purchase.services.orders import (
    PurchaseApprovalRequiredError,
    add_order_line,
    cancel_order,
    close_order,
    confirm_order,
    create_bulk_orders_from_requisitions,
    create_order,
    create_order_from_requisition,
    mark_order_in_transit,
    mark_order_partially_received,
    mark_order_received,
    open_order_dispute,
    resolve_order_dispute,
    send_order,
    submit_order_for_validation,
    validate_order,
)
from apps.purchase.services.price_watch import check_price_watch_target, create_price_watch_target
from apps.purchase.services.receiving import order_reception_variance, receive_order_line
from apps.purchase.services.requisitions import (
    add_requisition_line,
    approve_requisition,
    create_requisition,
    reject_requisition,
    submit_requisition,
)
from apps.purchase.services.rfq import (
    add_rfq_line,
    add_rfq_supplier,
    award_rfq,
    compute_comparison_table,
    create_rfq,
    record_rfq_response,
    send_rfq,
)


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


_ORDER_EXCEPTIONS = (
    ValidationError,
    InvalidOperation,
    ValueError,
    TransitionPermissionError,
    PurchaseApprovalRequiredError,
)


# ---------------------------------------------------------------------------
# Demandes d'achat (PurRequisition)
# ---------------------------------------------------------------------------

REQUISITION_COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="state", label="Statut"),
    Column(key="department", label="Departement"),
    Column(key="date_needed", label="Besoin le", searchable=False),
]


@login_required
def requisition_list(request: HttpRequest) -> HttpResponse:
    if request.method == "POST" and request.POST.get("action") == "bulk_create_orders":
        tenant = resolve_tenant(request)
        error = None
        raw_ids = request.POST.get("requisition_id", "")
        requisition_ids = [line.strip() for line in raw_ids.splitlines() if line.strip()]
        try:
            create_bulk_orders_from_requisitions(
                [uuid.UUID(rid) for rid in requisition_ids], tenant=tenant
            )
        except (ValidationError, ValueError) as exc:
            error = _error_message(exc)
        if error is None:
            return redirect("purchase:order_list")
        queryset = PurRequisition.objects.filter(is_active=True)
        return smart_table_response(
            request,
            table_key="purchase.requisitions",
            columns=REQUISITION_COLUMNS,
            queryset=queryset,
            page_template="purchase/requisition_list.html",
            page_context={"row_url_name": "purchase:requisition_detail", "error": error},
        )

    queryset = PurRequisition.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="purchase.requisitions",
        columns=REQUISITION_COLUMNS,
        queryset=queryset,
        page_template="purchase/requisition_list.html",
        page_context={"row_url_name": "purchase:requisition_detail"},
    )


@login_required
def requisition_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        try:
            requisition = create_requisition(
                tenant=tenant,
                requester=user,
                department=request.POST.get("department", ""),
                date_needed=parse_date(request.POST.get("date_needed", ""))
                or timezone.now().date(),
                justification=request.POST.get("justification", ""),
                source_document=request.POST.get("source_document", ""),
            )
        except (ValidationError, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("purchase:requisition_detail", requisition_id=requisition.id)

    return render(request, "purchase/requisition_create.html", {"error": error})


_REQUISITION_ACTIONS = {
    "submit": lambda requisition, user, _post: submit_requisition(requisition),
    "approve": lambda requisition, user, _post: approve_requisition(requisition, approved_by=user),
    "reject": lambda requisition, user, post: reject_requisition(
        requisition, reason=post.get("reason", "")
    ),
}


@login_required
def requisition_detail(request: HttpRequest, requisition_id: str) -> HttpResponse:
    requisition = get_object_or_404(PurRequisition, id=requisition_id)
    user = cast(User, request.user)
    error = None
    new_order = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "add_line":
                add_requisition_line(
                    requisition,
                    variant_id=uuid.UUID(post.get("variant_id", "")),
                    description=post.get("description", ""),
                    qty=Decimal(post.get("qty") or "1"),
                    uom=post.get("uom", ""),
                    preferred_supplier_id=uuid.UUID(post["preferred_supplier_id"])
                    if post.get("preferred_supplier_id")
                    else None,
                )
            elif action == "create_order":
                new_order = create_order_from_requisition(
                    requisition, partner_id=uuid.UUID(post.get("partner_id", ""))
                )
            else:
                handler = _REQUISITION_ACTIONS.get(action)
                if handler is not None:
                    handler(requisition, user, post)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            if new_order is not None:
                return redirect("purchase:order_detail", order_id=new_order.id)
            return redirect("purchase:requisition_detail", requisition_id=requisition.id)

    return render(
        request,
        "purchase/requisition_detail.html",
        {"requisition": requisition, "lines": requisition.lines.all(), "error": error},
    )


# ---------------------------------------------------------------------------
# Appels d'offres (PurRfq, RG-PUR-4)
# ---------------------------------------------------------------------------

RFQ_COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="state", label="Statut"),
    Column(key="date", label="Date", searchable=False),
    Column(key="deadline", label="Echeance", searchable=False),
]


@login_required
def rfq_list(request: HttpRequest) -> HttpResponse:
    queryset = PurRfq.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="purchase.rfqs",
        columns=RFQ_COLUMNS,
        queryset=queryset,
        page_template="purchase/rfq_list.html",
        page_context={"row_url_name": "purchase:rfq_detail"},
    )


@login_required
def rfq_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            rfq = create_rfq(
                tenant=tenant,
                date=parse_date(request.POST.get("date", "")) or timezone.now().date(),
                deadline=parse_date(request.POST.get("deadline", "")),
            )
        except (ValidationError, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("purchase:rfq_detail", rfq_id=rfq.id)

    return render(request, "purchase/rfq_create.html", {"error": error})


@login_required
def rfq_detail(request: HttpRequest, rfq_id: str) -> HttpResponse:
    rfq = get_object_or_404(PurRfq, id=rfq_id)
    user = cast(User, request.user)
    error = None
    new_order = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "add_line":
                add_rfq_line(
                    rfq,
                    variant_id=uuid.UUID(post.get("variant_id", "")),
                    description=post.get("description", ""),
                    qty=Decimal(post.get("qty") or "1"),
                    uom=post.get("uom", ""),
                )
            elif action == "add_supplier":
                add_rfq_supplier(rfq, partner_id=uuid.UUID(post.get("partner_id", "")))
            elif action == "send":
                send_rfq(rfq)
            elif action == "record_response":
                record_rfq_response(
                    rfq,
                    partner_id=uuid.UUID(post.get("resp_partner_id", "")),
                    date_received=parse_date(post.get("resp_date_received", ""))
                    or timezone.now().date(),
                    lines=[
                        {
                            "variant_id": uuid.UUID(post.get("resp_variant_id", "")),
                            "qty": Decimal(post.get("resp_qty") or "1"),
                            "unit_price_mga": Decimal(post.get("resp_unit_price_mga") or "0"),
                        }
                    ],
                    lead_time_days=int(post.get("resp_lead_time_days") or "0"),
                    validity_date=parse_date(post.get("resp_validity_date", "")),
                )
            elif action == "award":
                response = get_object_or_404(rfq.responses, id=post.get("response_id"))
                new_order = award_rfq(rfq, response, awarded_by=user)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            if new_order is not None:
                return redirect("purchase:order_detail", order_id=new_order.id)
            return redirect("purchase:rfq_detail", rfq_id=rfq.id)

    return render(
        request,
        "purchase/rfq_detail.html",
        {
            "rfq": rfq,
            "lines": rfq.lines.all(),
            "suppliers": rfq.suppliers.all(),
            "responses": rfq.responses.all(),
            "comparison": compute_comparison_table(rfq) if rfq.responses.exists() else [],
            "error": error,
        },
    )


# ---------------------------------------------------------------------------
# Commandes d'achat (PurOrder, FSM complete §5.6.4)
# ---------------------------------------------------------------------------

ORDER_COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="state", label="Statut"),
    Column(key="partner_id", label="Fournisseur", searchable=False),
    Column(key="origin", label="Origine", searchable=False),
    Column(key="amount_total_mga", label="Montant (MGA)", searchable=False),
]


@login_required
def order_list(request: HttpRequest) -> HttpResponse:
    queryset = PurOrder.objects.filter(is_active=True)
    state = request.GET.get("state")
    if state:
        queryset = queryset.filter(state=state)
    return smart_table_response(
        request,
        table_key="purchase.orders",
        columns=ORDER_COLUMNS,
        queryset=queryset,
        page_template="purchase/order_list.html",
        page_context={
            "row_url_name": "purchase:order_detail",
            "state_choices": PurOrder.STATE_CHOICES,
            "selected_state": state or "",
        },
    )


@login_required
def order_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            order = create_order(
                tenant=tenant,
                partner_id=uuid.UUID(request.POST.get("partner_id", "")),
                date=parse_date(request.POST.get("date", "")) or timezone.now().date(),
                date_expected=parse_date(request.POST.get("date_expected", "")),
                origin=request.POST.get("origin", PurOrder.ORIGIN_LOCAL),
                currency=request.POST.get("currency", "MGA"),
                incoterm=request.POST.get("incoterm", ""),
            )
        except (ValidationError, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("purchase:order_detail", order_id=order.id)

    return render(
        request,
        "purchase/order_create.html",
        {"error": error, "origin_choices": PurOrder.ORIGIN_CHOICES},
    )


_ORDER_ACTIONS = {
    "submit": lambda order, user, _post: submit_order_for_validation(order, user),
    "validate": lambda order, user, _post: validate_order(order, user),
    "send": lambda order, user, _post: send_order(order, user),
    "confirm": lambda order, user, _post: confirm_order(order, user),
    "in_transit": lambda order, user, _post: mark_order_in_transit(order, user),
    "partially_receive": lambda order, user, _post: mark_order_partially_received(order, user),
    "receive": lambda order, user, _post: mark_order_received(order, user),
    "close": lambda order, user, _post: close_order(order, user),
    "cancel": lambda order, user, post: cancel_order(order, user, reason=post.get("reason", "")),
    "open_dispute": lambda order, user, post: open_order_dispute(
        order, user, reason=post.get("reason", "")
    ),
    "resolve_dispute": lambda order, user, _post: resolve_order_dispute(order, user),
}


@login_required
def order_detail(request: HttpRequest, order_id: str) -> HttpResponse:
    order = get_object_or_404(PurOrder, id=order_id)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "add_line":
                add_order_line(
                    order,
                    variant_id=uuid.UUID(post.get("variant_id", "")),
                    description=post.get("description", ""),
                    qty=Decimal(post.get("qty") or "1"),
                    unit_price_mga=Decimal(post.get("unit_price_mga") or "0"),
                    uom=post.get("uom", ""),
                    discount_pct=Decimal(post.get("discount_pct") or "0"),
                    tax_pct=Decimal(post.get("tax_pct") or "0"),
                    supplier_sku=post.get("supplier_sku", ""),
                )
            elif action == "receive_line":
                line = get_object_or_404(PurOrderLine, id=post.get("line_id"), order=order)
                receive_order_line(
                    line,
                    qty_received_now=Decimal(post.get("qty_received_now") or "0"),
                    quality_status=post.get("quality_status") or "conforme",
                    user=user,
                    notes=post.get("receive_notes", ""),
                )
            elif action == "record_invoice":
                line = get_object_or_404(PurOrderLine, id=post.get("invoice_line_id"), order=order)
                # RG-PUR-6 (§5.6.6, acceptance test n°4) : `record_supplier_
                # invoice` execute le controle 3 voies AVANT toute
                # materialisation comptable — jamais un appel direct a
                # `mark_order_invoiced` depuis l'ecran (qui contournerait le
                # controle). Le resultat (bloque/facture) reste visible
                # apres coup via `order.dispute_reason`/`order.state`/
                # `line.qty_invoiced` re-charges au re-rendu de la fiche.
                record_supplier_invoice(
                    order,
                    invoice_lines=[
                        {
                            "order_line_id": line.id,
                            "qty_invoiced": Decimal(post.get("invoice_qty") or "0"),
                            "unit_price_mga": Decimal(post.get("invoice_unit_price_mga") or "0"),
                        }
                    ],
                    date=parse_date(post.get("invoice_date", "")) or timezone.now().date(),
                    user=user,
                )
            else:
                handler = _ORDER_ACTIONS.get(action)
                if handler is not None:
                    handler(order, user, post)
        except _ORDER_EXCEPTIONS as exc:
            error = _error_message(exc)
        else:
            return redirect("purchase:order_detail", order_id=order.id)

    return render(
        request,
        "purchase/order_detail.html",
        {
            "order": order,
            "lines": order.lines.all(),
            "reception_variance": order_reception_variance(order),
            "error": error,
        },
    )


# ---------------------------------------------------------------------------
# PurCra — compte rendu d'activite achats (liste + creation + actions
# inline, cf. note de deviation en tete de module)
# ---------------------------------------------------------------------------


@login_required
def cra_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "create":
                order = None
                if post.get("order_id"):
                    order = get_object_or_404(PurOrder, id=post.get("order_id"))
                create_cra(
                    tenant=tenant,
                    date=parse_date(post.get("date", "")) or timezone.now().date(),
                    buyer=user,
                    partner_id=uuid.UUID(post.get("partner_id", "")),
                    activity_type=post.get("activity_type", PurCra.TYPE_SOURCING),
                    hours=Decimal(post.get("hours") or "0"),
                    order=order,
                    comment=post.get("comment", ""),
                )
            else:
                cra = get_object_or_404(PurCra, id=post.get("cra_id"))
                if action == "submit":
                    submit_cra(cra)
                elif action == "validate":
                    validate_cra(cra, validated_by=user)
                elif action == "reject":
                    reject_cra(cra, reason=post.get("reason", ""))
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("purchase:cra_list")

    entries = PurCra.objects.filter(is_active=True).order_by("-date")
    return render(
        request,
        "purchase/cra_list.html",
        {"entries": entries, "activity_types": PurCra.ACTIVITY_TYPE_CHOICES, "error": error},
    )


# ---------------------------------------------------------------------------
# PurCri — compte rendu d'incident achats (liste + creation + actions
# inline, cf. note de deviation en tete de module)
# ---------------------------------------------------------------------------


@login_required
def cri_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "create":
                order = None
                if post.get("order_id"):
                    order = get_object_or_404(PurOrder, id=post.get("order_id"))
                create_cri(
                    tenant=tenant,
                    date=parse_date(post.get("date", "")) or timezone.now().date(),
                    type=post.get("type", PurCri.TYPE_RETARD),
                    partner_id=uuid.UUID(post.get("partner_id", "")),
                    description=post.get("description", ""),
                    order=order,
                    impact=post.get("impact", ""),
                    cost_mga=Decimal(post.get("cost_mga") or "0"),
                )
            elif action == "close":
                cri = get_object_or_404(PurCri, id=post.get("cri_id"))
                close_cri(cri, action_taken=post.get("action_taken", ""))
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("purchase:cri_list")

    entries = PurCri.objects.filter(is_active=True).order_by("-date")
    return render(
        request,
        "purchase/cri_list.html",
        {"entries": entries, "type_choices": PurCri.TYPE_CHOICES, "error": error},
    )


# ---------------------------------------------------------------------------
# PRC1-3 — Veille prix fournisseurs Chine/Europe (cf. plan). Meme deviation
# assumee "liste + creation + actions inline" que CRA/CRI ci-dessus (pas de
# fiche detail dediee par cible) : `PrcPriceWatchTarget` a un cycle de vie
# trivial (pas de FSM), une ligne de tableau porte deja toute l'information
# utile ; l'historique des releves d'UNE cible est expose sur une page
# dediee (`price_watch_history`, un besoin de lecture distinct — pas une
# action de transition — qui justifie sa propre page).
# ---------------------------------------------------------------------------


@login_required
def price_watch_list(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "create":
                material_reference_id = post.get("material_reference_id") or ""
                variant_id = post.get("variant_id") or ""
                create_price_watch_target(
                    tenant=tenant,
                    platform_code=post.get("platform_code", PrcPriceWatchTarget.PLATFORM_AUTRE),
                    search_query_or_url=post.get("search_query_or_url", ""),
                    currency=post.get("currency", "MGA"),
                    frequency=post.get("frequency", PrcPriceWatchTarget.FREQUENCY_MONTHLY),
                    material_reference_id=uuid.UUID(material_reference_id)
                    if material_reference_id
                    else None,
                    variant_id=uuid.UUID(variant_id) if variant_id else None,
                )
            elif action == "check":
                target = get_object_or_404(PrcPriceWatchTarget, id=post.get("target_id"))
                check_price_watch_target(target)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("purchase:price_watch_list")

    targets = PrcPriceWatchTarget.objects.filter(is_active=True).order_by("-created_at")
    return render(
        request,
        "purchase/price_watch_list.html",
        {
            "targets": targets,
            "platform_choices": PrcPriceWatchTarget.PLATFORM_CHOICES,
            "frequency_choices": PrcPriceWatchTarget.FREQUENCY_CHOICES,
            "error": error,
        },
    )


@login_required
def price_watch_history(request: HttpRequest, target_id: uuid.UUID) -> HttpResponse:
    target = get_object_or_404(PrcPriceWatchTarget, id=target_id)
    snapshots = target.snapshots.order_by("-observed_at")
    return render(
        request,
        "purchase/price_watch_history.html",
        {"target": target, "snapshots": snapshots},
    )
