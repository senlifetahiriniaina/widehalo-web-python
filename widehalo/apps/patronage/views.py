"""Ecrans HTMX minimaux du module `patronage` (U1) : liste des patrons,
detail avec pieces/mesures gradees + lien de telechargement du dossier
technique, formulaire de creation. Meme patron que `apps.accounting.views`."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models.user import User
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.patronage.models import PatPattern, PatPatternPiece, PatSizeChart
from apps.patronage.services.consumption import (
    compute_consumption,
    compute_marker,
    push_to_bom,
    revert_push_to_bom,
)
from apps.patronage.services.eco import (
    EcoApprovalRequiredError,
    impacted_boms,
    validate_pattern_version,
)
from apps.patronage.services.grading import apply_grading
from apps.patronage.services.patterns import (
    add_pattern_piece,
    create_pattern,
    generate_piece_geometry,
    new_pattern_version,
)

# Points de mesure geres par le mini-formulaire de generation de geometrie
# (U4) : suffisants pour les 4 gabarits parametriques simples de
# `services/patterns.py::_PIECE_REQUIREMENTS` (chemise/tshirt/pantalon/jupe).
# Volontairement fixe plutot qu'un formulaire dynamique par point de mesure.
GEOMETRY_MEASUREMENT_CODES = ("tour_poitrine", "tour_taille", "longueur")


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


def _parse_uuid(raw: str | None) -> uuid.UUID | None:
    raw = (raw or "").strip()
    return uuid.UUID(raw) if raw else None


def _parse_size_ratio(raw: str) -> dict[str, int]:
    """Parse "S:2,M:3" -> {"S": 2, "M": 3} (U4, mini-formulaire plan de coupe)."""
    ratio: dict[str, int] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        size, _sep, qty = part.partition(":")
        ratio[size.strip()] = int(qty.strip())
    return ratio


COLUMNS = [
    Column(key="code", label="Code"),
    Column(key="name", label="Nom"),
    Column(key="version", label="Version", searchable=False),
    Column(key="state", label="Statut"),
]


@login_required
def pattern_list(request: HttpRequest) -> HttpResponse:
    queryset = PatPattern.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="patronage.patterns",
        columns=COLUMNS,
        queryset=queryset,
        page_template="patronage/list.html",
        page_context={"row_url_name": "patronage:detail"},
    )


@login_required
def pattern_detail(request: HttpRequest, pattern_id: str) -> HttpResponse:
    pattern = get_object_or_404(PatPattern, id=pattern_id)
    user = cast(User, request.user)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        redirect_pattern_id = pattern.id
        try:
            if action == "validate":
                validate_pattern_version(pattern, requested_by=user)
            elif action == "add_piece":
                add_pattern_piece(
                    pattern,
                    code=request.POST.get("code", ""),
                    name=request.POST.get("name", ""),
                    qty_per_garment=int(request.POST.get("qty_per_garment") or 1),
                    material_variant_id=_parse_uuid(request.POST.get("material_variant_id")),
                )
            elif action == "generate_geometry":
                piece = get_object_or_404(
                    PatPatternPiece, id=request.POST.get("piece_id"), pattern=pattern
                )
                graded_measurements = {}
                for code in GEOMETRY_MEASUREMENT_CODES:
                    raw = (request.POST.get(code) or "").strip()
                    if raw:
                        graded_measurements[code] = Decimal(raw)
                generate_piece_geometry(
                    piece,
                    size=request.POST.get("size", ""),
                    graded_measurements=graded_measurements,
                )
            elif action == "compute_consumption":
                compute_consumption(
                    pattern,
                    size=request.POST.get("size", ""),
                    material_variant_id=_parse_uuid(request.POST.get("material_variant_id")),
                    width_cm=Decimal(request.POST.get("width_cm") or "0"),
                    waste_pct=Decimal(request.POST.get("waste_pct") or "0"),
                )
            elif action == "compute_marker":
                compute_marker(
                    pattern,
                    material_variant_id=_parse_uuid(request.POST.get("material_variant_id")),
                    fabric_width_cm=Decimal(request.POST.get("fabric_width_cm") or "0"),
                    size_ratio=_parse_size_ratio(request.POST.get("size_ratio", "")),
                )
            elif action == "push_to_bom":
                push_to_bom(
                    pattern,
                    bom_id=_parse_uuid(request.POST.get("bom_id")),
                    material_variant_id=_parse_uuid(request.POST.get("material_variant_id")),
                    actor=user,
                )
            elif action == "revert_push_to_bom":
                revert_push_to_bom(
                    pattern,
                    bom_id=_parse_uuid(request.POST.get("bom_id")),
                    material_variant_id=_parse_uuid(request.POST.get("material_variant_id")),
                    actor=user,
                )
            elif action == "new_version":
                redirect_pattern_id = new_pattern_version(pattern).id
        except EcoApprovalRequiredError as exc:
            error = str(exc)
        except (ValidationError, ValueError, InvalidOperation) as exc:
            error = _error_message(exc)
        else:
            return redirect("patronage:detail", pattern_id=redirect_pattern_id)

    graded = None
    try:
        graded = apply_grading(pattern.size_chart)
    except ValidationError:
        graded = None

    return render(
        request,
        "patronage/detail.html",
        {
            "pattern": pattern,
            "pieces": pattern.pieces.all(),
            "graded": graded,
            "geometry_measurement_codes": GEOMETRY_MEASUREMENT_CODES,
            "consumptions": pattern.consumptions.all(),
            "markers": pattern.markers.all(),
            "impacted_boms": impacted_boms(pattern),
            "error": error,
        },
    )


@login_required
def pattern_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    size_charts = PatSizeChart.objects.filter(tenant=tenant)
    error = None

    if request.method == "POST":
        try:
            size_chart = get_object_or_404(PatSizeChart, id=request.POST.get("size_chart_id"))
            pattern = create_pattern(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                size_chart=size_chart,
            )
        except ValidationError as exc:
            error = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        else:
            return redirect("patronage:detail", pattern_id=pattern.id)

    return render(request, "patronage/create.html", {"size_charts": size_charts, "error": error})
