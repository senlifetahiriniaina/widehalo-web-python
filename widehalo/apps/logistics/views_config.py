"""Ecrans de configuration du module `logistics` (LOG7), regroupes sous le
hub "Parametres" (meme convention que `apps.purchase.views_config`/
`apps.mrp.views_config`) : types d'emballage, prestataires + tarifs de
fret, codes SH.

Prestataires et tarifs de fret sont volontairement CONSOLIDES sur une
seule page (`config_service_providers.html`) plutot que deux — un tarif
n'a de sens que rattache a un prestataire deja cree, meme critere de
consolidation que `stocks` a l'etape ST8 face au plafond de gabarits
(`tests/architecture/test_budget.py`), applique ici par discipline meme
si le plafond actuel (200) laisse une marge confortable."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _

from apps.core.services.permissions import screen_forbidden, screen_permission
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant
from apps.logistics.models import LogFreightTariff, LogHsCode, LogPackagingType, LogServiceProvider
from apps.logistics.services.customs import create_hs_code
from apps.logistics.services.freight import create_freight_tariff, create_service_provider

PACKAGING_TYPE_COLUMNS = [
    Column(key="code", label=_("Code")),
    Column(key="name", label=_("Nom")),
    Column(key="volume_m3", label=_("Volume (m³)"), searchable=False),
]

SERVICE_PROVIDER_COLUMNS = [
    Column(key="name", label=_("Nom")),
    Column(key="type", label=_("Type")),
]

HS_CODE_COLUMNS = [
    Column(key="code", label=_("Code SH")),
    Column(key="description", label=_("Désignation")),
    Column(key="duty_rate_pct", label=_("Droit (%)"), searchable=False),
]


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


@login_required
@screen_permission("logistics.view_logpackagingtype")
def config_index(request: HttpRequest) -> HttpResponse:
    return render(request, "logistics/config_index.html", {})


@login_required
@screen_permission("logistics.view_logpackagingtype")
def config_packaging_types(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "logistics.add_logpackagingtype")
        if refus is not None:
            return refus

    if request.method == "POST":
        packaging_type = LogPackagingType(
            tenant=tenant,
            code=request.POST.get("code", ""),
            name=request.POST.get("name", ""),
        )
        try:
            packaging_type.tare_weight_kg = Decimal(request.POST.get("tare_weight_kg") or "0")
            if request.POST.get("max_weight_kg"):
                packaging_type.max_weight_kg = Decimal(request.POST["max_weight_kg"])
            if request.POST.get("volume_m3"):
                packaging_type.volume_m3 = Decimal(request.POST["volume_m3"])
            packaging_type.full_clean()
        except (ValidationError, InvalidOperation) as exc:
            error = _error_message(exc)
        else:
            packaging_type.save()
            return redirect("logistics:config_packaging_types")

    return smart_table_response(
        request,
        table_key="logistics.packaging_types",
        columns=PACKAGING_TYPE_COLUMNS,
        queryset=LogPackagingType.objects.filter(tenant=tenant, is_active=True),
        page_template="logistics/config_packaging_types.html",
        page_context={"error": error},
    )


@login_required
@screen_permission("logistics.view_logserviceprovider")
def config_service_providers(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "logistics.add_logserviceprovider")
        if refus is not None:
            return refus

    if request.method == "POST":
        action = request.POST.get("action", "")
        post = request.POST
        try:
            if action == "create_provider":
                create_service_provider(
                    tenant,
                    code=post.get("code", ""),
                    name=post.get("name", ""),
                    type=post.get("type", LogServiceProvider.TYPE_CARRIER),
                    contact_phone=post.get("contact_phone", ""),
                    contact_email=post.get("contact_email", ""),
                )
            elif action == "create_tariff":
                provider = get_object_or_404(LogServiceProvider, id=post.get("provider_id", ""))
                create_freight_tariff(
                    provider,
                    origin=post.get("origin", ""),
                    destination=post.get("destination", ""),
                    price_mga=Decimal(post.get("price_mga") or "0"),
                    transit_days=int(post.get("transit_days") or "0"),
                    price_per_kg_mga=Decimal(post["price_per_kg_mga"])
                    if post.get("price_per_kg_mga")
                    else None,
                    valid_from=parse_date(post.get("valid_from", "")),
                    valid_to=parse_date(post.get("valid_to", "")),
                )
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = _error_message(exc)
        else:
            return redirect("logistics:config_service_providers")

    # Le SmartTable porte les PRESTATAIRES — l'entite principale de l'ecran.
    # Les tarifs restent une table de detail rattachee : un tarif n'a de sens
    # qu'adosse a un prestataire deja cree (cf. docstring de module), et les
    # paginer separement couperait ce lien a l'ecran.
    return smart_table_response(
        request,
        table_key="logistics.service_providers",
        columns=SERVICE_PROVIDER_COLUMNS,
        queryset=LogServiceProvider.objects.filter(tenant=tenant, is_active=True),
        page_template="logistics/config_service_providers.html",
        page_context={
            "tariffs": LogFreightTariff.objects.filter(
                tenant=tenant, is_active=True
            ).select_related("provider"),
            "type_choices": LogServiceProvider.TYPE_CHOICES,
            "error": error,
        },
    )


@login_required
@screen_permission("logistics.view_loghscode")
def config_hs_codes(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        refus = screen_forbidden(request, "logistics.add_loghscode")
        if refus is not None:
            return refus

    if request.method == "POST":
        try:
            create_hs_code(
                tenant,
                code=request.POST.get("code", ""),
                description=request.POST.get("description", ""),
                duty_rate_pct=Decimal(request.POST.get("duty_rate_pct") or "0"),
                valid_from=parse_date(request.POST.get("valid_from", "")),
                valid_to=parse_date(request.POST.get("valid_to", "")),
            )
        except (ValidationError, InvalidOperation) as exc:
            error = _error_message(exc)
        else:
            return redirect("logistics:config_hs_codes")

    return smart_table_response(
        request,
        table_key="logistics.hs_codes",
        columns=HS_CODE_COLUMNS,
        queryset=LogHsCode.objects.filter(tenant=tenant, is_active=True),
        page_template="logistics/config_hs_codes.html",
        page_context={"error": error},
    )
