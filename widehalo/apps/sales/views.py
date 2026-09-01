"""Ecrans HTMX minimaux du module `sales` (§5.5.7 restant, S7) : liste
devis/commandes (SmartTable), fiches detail avec bandeau de workflow
(boutons d'action), formulaires de creation, conversion devis->commande.
Meme patron que `apps.mrp.views` (session-authentifie, appel direct aux
`services/*`, jamais l'API JWT interne)."""

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
from django.utils.translation import gettext as _

from apps.catalog.services.public import (
    get_variant_reference,
    is_variant_sellable,
    list_sellable_variants,
)
from apps.core.models.user import User
from apps.core.services.permissions import user_role_codes
from apps.core.services.workflow import TransitionPermissionError
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.sales.models import SalesOrder, SalesQuotation
from apps.sales.services.invoicing import invoice_order
from apps.sales.services.orders import (
    add_order_line,
    cancel_order,
    close_order,
    confirm_order,
    create_order,
    create_order_from_quotation,
    mark_delivered,
    send_order,
    start_preparation,
    unblock_order,
)
from apps.sales.services.quotations import (
    accept_quotation,
    add_quotation_line,
    create_quotation,
    decline_quotation,
    send_quotation,
)

# RG-SAL-5 : roles autorises a voir `margin_pct` en ecran — meme ensemble
# que `apps.core.services.permissions.SENSITIVE_FIELDS["sales.SalesOrderLine"]`.
# Choix documente (cf. plan/RG-SAL-5) : verification directe des roles de
# session plutot qu'un aller-retour par `filter_fields_for_role` (qui
# masque des CLES de dict, pas des colonnes de gabarit HTML) — le gabarit
# a simplement besoin d'un booleen "affiche la colonne Marge ou non".
_MARGIN_VISIBLE_ROLES = {"direction", "admin", "resp_commercial"}


def _can_see_margin(user: User) -> bool:
    return bool(user_role_codes(user) & _MARGIN_VISIBLE_ROLES)


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


QUOTATION_COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="state", label="Statut"),
    Column(key="amount_total", label="Montant", searchable=False),
]

ORDER_COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="state", label="Statut"),
    Column(key="partner_id", label="Partenaire", searchable=False),
    Column(key="salesperson", label="Commercial", searchable=False),
    Column(key="amount_total_mga", label="Montant (MGA)", searchable=False),
]


@login_required
def quotation_list(request: HttpRequest) -> HttpResponse:
    queryset = SalesQuotation.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="sales.quotations",
        columns=QUOTATION_COLUMNS,
        queryset=queryset,
        page_template="sales/quotation_list.html",
        page_context={"row_url_name": "sales:quotation_detail"},
    )


@login_required
def quotation_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        try:
            quotation = create_quotation(
                tenant=tenant,
                partner_id=uuid.UUID(request.POST.get("partner_id", "")),
                date=parse_date(request.POST.get("date", "")) or timezone.now().date(),
                salesperson=user,
                contact=request.POST.get("contact", ""),
            )
        except (ValidationError, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("sales:quotation_detail", quotation_id=quotation.id)

    return render(request, "sales/quotation_create.html", {"error": error})


def _resolve_line_from_post(post) -> dict:
    """Une ligne de devis/commande vient soit d'un produit CATALOGUE
    (`variant_id` pose), soit d'une ligne hors catalogue (`is_custom`).
    Cote serveur, un `variant_id` n'est JAMAIS accepte tel quel — revalide
    contre `catalog.services.public.is_variant_sellable` avant de creer la
    ligne (le filtrage du selecteur cote ecran, cf.
    `_partner_picker`-like, reste contournable par un POST direct)."""
    variant_id_raw = (post.get("variant_id") or "").strip()
    if variant_id_raw:
        variant_id = uuid.UUID(variant_id_raw)
        if not is_variant_sellable(variant_id):
            raise ValidationError(_("Ce produit n'est pas vendable."))
        description = post.get("description") or get_variant_reference(variant_id)
        return {"variant_id": variant_id, "description": description, "is_custom": False}
    return {"description": post.get("description", ""), "is_custom": True}


_QUOTATION_ACTIONS = {
    "send": lambda quotation, _post: send_quotation(quotation),
    "accept": lambda quotation, _post: accept_quotation(quotation),
    "decline": lambda quotation, post: decline_quotation(quotation, reason=post.get("reason", "")),
}


@login_required
def quotation_detail(request: HttpRequest, quotation_id: str) -> HttpResponse:
    quotation = get_object_or_404(SalesQuotation, id=quotation_id)
    user = cast(User, request.user)
    error = None
    new_order = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "add_line":
                add_quotation_line(
                    quotation,
                    qty=Decimal(post.get("qty") or "1"),
                    unit_price=Decimal(post.get("unit_price")) if post.get("unit_price") else None,
                    sequence=quotation.lines.count(),
                    **_resolve_line_from_post(post),
                )
            elif action == "convert_to_order":
                new_order = create_order_from_quotation(quotation)
            else:
                handler = _QUOTATION_ACTIONS.get(action)
                if handler is not None:
                    handler(quotation, post)
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            if new_order is not None:
                return redirect("sales:order_detail", order_id=new_order.id)
            return redirect("sales:quotation_detail", quotation_id=quotation.id)

    return render(
        request,
        "sales/quotation_detail.html",
        {
            "quotation": quotation,
            "lines": quotation.lines.all(),
            "can_see_margin": _can_see_margin(user),
            "sellable_variants": list_sellable_variants(),
            "error": error,
        },
    )


@login_required
def order_list(request: HttpRequest) -> HttpResponse:
    queryset = SalesOrder.objects.filter(is_active=True)
    state = request.GET.get("state")
    partner_id = request.GET.get("partner_id")
    salesperson_id = request.GET.get("salesperson_id")
    if state:
        queryset = queryset.filter(state=state)
    if partner_id:
        queryset = queryset.filter(partner_id=partner_id)
    if salesperson_id:
        queryset = queryset.filter(salesperson_id=salesperson_id)
    return smart_table_response(
        request,
        table_key="sales.orders",
        columns=ORDER_COLUMNS,
        queryset=queryset,
        page_template="sales/order_list.html",
        page_context={
            "row_url_name": "sales:order_detail",
            "state_choices": SalesOrder.STATE_CHOICES,
            "selected_state": state or "",
        },
    )


@login_required
def order_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        try:
            order = create_order(
                tenant=tenant,
                partner_id=uuid.UUID(request.POST.get("partner_id", "")),
                date=parse_date(request.POST.get("date", "")) or timezone.now().date(),
                salesperson=user,
                contact=request.POST.get("contact", ""),
                is_export=bool(request.POST.get("is_export")),
                incoterm=request.POST.get("incoterm", ""),
            )
        except (ValidationError, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("sales:order_detail", order_id=order.id)

    return render(request, "sales/order_create.html", {"error": error})


_ORDER_ACTIONS = {
    "send": lambda order, user, _post: send_order(order, user),
    "confirm": lambda order, user, _post: confirm_order(order, user),
    "unblock": lambda order, user, _post: unblock_order(order, user),
    "start_preparation": lambda order, user, _post: start_preparation(order, user),
    "deliver_partial": lambda order, user, _post: mark_delivered(order, user, partial=True),
    "deliver_full": lambda order, user, _post: mark_delivered(order, user, partial=False),
    "close": lambda order, user, _post: close_order(order, user),
    "cancel": lambda order, user, post: cancel_order(order, user, reason=post.get("reason", "")),
}


@login_required
def order_detail(request: HttpRequest, order_id: str) -> HttpResponse:
    order = get_object_or_404(SalesOrder, id=order_id)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "add_line":
                add_order_line(
                    order,
                    qty=Decimal(post.get("qty") or "1"),
                    unit_price=Decimal(post.get("unit_price")) if post.get("unit_price") else None,
                    billing_policy=post.get("billing_policy", "on_ordered_qty"),
                    sequence=order.lines.count(),
                    **_resolve_line_from_post(post),
                )
            elif action == "invoice":
                invoice_order(order, user)
            else:
                handler = _ORDER_ACTIONS.get(action)
                if handler is not None:
                    handler(order, user, post)
        except (
            ValidationError,
            InvalidOperation,
            ValueError,
            TransitionPermissionError,
        ) as exc:
            error = _error_message(exc)
        else:
            return redirect("sales:order_detail", order_id=order.id)

    return render(
        request,
        "sales/order_detail.html",
        {
            "order": order,
            "lines": order.lines.all(),
            "can_see_margin": _can_see_margin(user),
            "sellable_variants": list_sellable_variants(),
            "error": error,
        },
    )
