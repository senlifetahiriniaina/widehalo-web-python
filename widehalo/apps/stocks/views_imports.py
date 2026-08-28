"""Ecrans d'import de quantites initiales de stock (session HTMX, jamais
l'API JWT en interne) — meme discipline que
`apps.accounting.views_imports` (formulaire d'import + ecran de resolution
des lignes en anomalie par lot), rattaches au menu `stocks` (pas au hub
"Configuration" — une ouverture de stock est un acte ponctuel de migration,
pas un parametrage recurrent, meme categorie que l'import du journal de
caisse de `accounting`, qui est lui aussi hors du hub config)."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.core.views.tenant_web import resolve_tenant
from apps.stocks.models import StkImportBatch, StkImportRow, StkLocation, StkWarehouse
from apps.stocks.services.stock_import import (
    import_stock_quantities_xlsx,
    qualify_import_row,
    resolve_import_row,
)


@login_required
def imports_index(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    summary = None
    error = None

    if request.method == "POST":
        uploaded_file = request.FILES.get("file")
        if uploaded_file is None:
            error = _("Aucun fichier fourni.")
        else:
            try:
                summary = import_stock_quantities_xlsx(
                    tenant, uploaded_file.read(), filename=uploaded_file.name
                )
            except ValueError as exc:
                error = str(exc)

    batches = StkImportBatch.objects.filter(tenant=tenant).order_by("-created_at")[:20]
    return render(
        request,
        "stocks/imports/index.html",
        {"summary": summary, "error": error, "batches": batches},
    )


@login_required
def imports_batch_detail(request: HttpRequest, batch_id: str) -> HttpResponse:
    tenant = resolve_tenant(request)
    batch = get_object_or_404(StkImportBatch, tenant=tenant, id=batch_id)
    rows = batch.rows.order_by("row_number")
    warehouses = StkWarehouse.objects.filter(tenant=tenant, is_active=True).order_by("code")
    return render(
        request,
        "stocks/imports/batch_detail.html",
        {"batch": batch, "rows": rows, "warehouses": warehouses},
    )


@login_required
def imports_row_resolve(request: HttpRequest, row_id: str) -> HttpResponse:
    tenant = resolve_tenant(request)
    row = get_object_or_404(StkImportRow, tenant=tenant, id=row_id)

    if request.method == "POST":
        if request.POST.get("discard"):
            resolve_import_row(row, discard=True)
        else:
            warehouse_id = request.POST.get("warehouse_id") or None
            warehouse = (
                StkWarehouse.objects.filter(tenant=tenant, id=warehouse_id).first()
                if warehouse_id
                else None
            )
            location_id = request.POST.get("location_id") or None
            location = (
                StkLocation.objects.filter(tenant=tenant, id=location_id).first()
                if location_id
                else None
            )
            variant_code = request.POST.get("variant_code") or None
            qty_raw = request.POST.get("qty") or ""
            try:
                qty = Decimal(qty_raw) if qty_raw else None
            except InvalidOperation:
                qty = None
            resolve_import_row(
                row,
                variant_code=variant_code,
                warehouse=warehouse,
                location=location,
                qty=qty,
            )

    return redirect("stocks:imports_batch_detail", batch_id=row.batch_id)


@login_required
def imports_row_qualify(request: HttpRequest, row_id: str) -> HttpResponse:
    """Ecran "à qualifier" (chantier RG-QUALIF) — extourne le mouvement
    placeholder deja valide et en recree/valide un nouveau correctement
    attribue (cf. docstring de `services/stock_import.py`)."""
    tenant = resolve_tenant(request)
    row = get_object_or_404(StkImportRow, tenant=tenant, id=row_id)

    if request.method == "POST":
        variant_id_raw = request.POST.get("variant_id") or None
        variant_id = uuid.UUID(variant_id_raw) if variant_id_raw else None
        location_id = request.POST.get("location_id") or None
        location = (
            StkLocation.objects.filter(tenant=tenant, id=location_id).first()
            if location_id
            else None
        )
        qualify_import_row(row, variant_id=variant_id, location=location, qualified_by=request.user)

    return redirect("stocks:imports_batch_detail", batch_id=row.batch_id)
