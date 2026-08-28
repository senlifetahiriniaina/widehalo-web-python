"""Ecrans de configuration du module `stocks` (ST8), regroupes sous le hub
"Parametres" (meme convention que `apps.purchase.views_config`/
`apps.mrp.views_config`) : entrepots/emplacements (imbriques, ST1),
types de defaut (ST1), exceptions de stock negatif (RG-STK-10, ST7).

Rendus sur le MEME gabarit unique que `apps.stocks.views`
(`stocks/index.html`, `active_tab="config"`) — cf. sa docstring de module
pour la justification complete de ce choix (plafond `test_budget.py`,
1 seul emplacement de gabarit disponible pour tout ST8)."""

from __future__ import annotations

import uuid
from decimal import InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models.user import User
from apps.core.views.tenant_web import resolve_tenant
from apps.stocks.models import (
    StkDefectType,
    StkLocation,
    StkNegativeStockException,
    StkWarehouse,
)
from apps.stocks.services.defect_types import create_defect_type
from apps.stocks.services.negative_stock import (
    grant_negative_stock_exception,
    revoke_negative_stock_exception,
)
from apps.stocks.services.warehouses import create_location, create_warehouse

_EXC = (ValidationError, InvalidOperation, ValueError)


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


@login_required
def config_index(request: HttpRequest) -> HttpResponse:
    return redirect("stocks:config_warehouses")


@login_required
def config_warehouses(request: HttpRequest) -> HttpResponse:
    """Entrepots + emplacements imbriques (ST1) — meme page, un formulaire
    de creation d'entrepot et un formulaire de creation d'emplacement
    (avec parent optionnel), meme discipline "config imbriquee sur une
    seule page" que `apps.mrp.views_config` (atelier/poste de travail)."""
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "create_warehouse":
                create_warehouse(
                    tenant=tenant,
                    code=post.get("code", ""),
                    name=post.get("name", ""),
                    type=post.get("type", StkWarehouse.TYPE_PRINCIPAL),
                    address=post.get("address", ""),
                )
            elif action == "create_location":
                warehouse = get_object_or_404(StkWarehouse, id=post.get("warehouse_id"))
                parent = (
                    get_object_or_404(StkLocation, id=post.get("parent_id"))
                    if post.get("parent_id")
                    else None
                )
                create_location(
                    tenant=tenant,
                    warehouse=warehouse,
                    code=post.get("loc_code", ""),
                    name=post.get("loc_name", ""),
                    type=post.get("loc_type", StkLocation.TYPE_INTERNE),
                    parent=parent,
                    is_scrap=bool(post.get("is_scrap")),
                )
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:config_warehouses")

    warehouses = StkWarehouse.objects.filter(is_active=True)
    locations = StkLocation.objects.filter(is_active=True).select_related("warehouse", "parent")
    return render(
        request,
        "stocks/index.html",
        {
            "active_tab": "config",
            "config_subtab": "warehouses",
            "warehouses": warehouses,
            "locations": locations,
            "warehouse_type_choices": StkWarehouse.TYPE_CHOICES,
            "location_type_choices": StkLocation.TYPE_CHOICES,
            "error": error,
        },
    )


@login_required
def config_defect_types(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        post = request.POST
        try:
            create_defect_type(
                tenant=tenant,
                code=post.get("code", ""),
                name=post.get("name", ""),
                category=post.get("category", StkDefectType.CATEGORY_TISSU),
                severity=post.get("severity", StkDefectType.SEVERITY_MINEUR),
                default_action=post.get("default_action", ""),
            )
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:config_defect_types")

    defect_types = StkDefectType.objects.filter(is_active=True)
    return render(
        request,
        "stocks/index.html",
        {
            "active_tab": "config",
            "config_subtab": "defect_types",
            "defect_types": defect_types,
            "category_choices": StkDefectType.CATEGORY_CHOICES,
            "severity_choices": StkDefectType.SEVERITY_CHOICES,
            "error": error,
        },
    )


@login_required
def config_negative_stock(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "grant":
                grant_negative_stock_exception(
                    tenant=tenant,
                    variant_id=uuid.UUID(post.get("variant_id", "")),
                    authorized_by=user,
                    reason=post.get("reason", ""),
                )
            elif action == "revoke":
                exception = get_object_or_404(
                    StkNegativeStockException, id=post.get("exception_id")
                )
                revoke_negative_stock_exception(exception, reason=post.get("reason", ""))
        except _EXC as exc:
            error = _error_message(exc)
        else:
            return redirect("stocks:config_negative_stock")

    exceptions = StkNegativeStockException.objects.filter(is_active=True)
    return render(
        request,
        "stocks/index.html",
        {
            "active_tab": "config",
            "config_subtab": "negative_stock",
            "exceptions": exceptions,
            "error": error,
        },
    )
