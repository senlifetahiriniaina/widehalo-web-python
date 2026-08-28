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

from apps.core.views.tenant_web import resolve_tenant
from apps.logistics.models import LogFreightTariff, LogHsCode, LogPackagingType, LogServiceProvider
from apps.logistics.services.customs import create_hs_code
from apps.logistics.services.freight import create_freight_tariff, create_service_provider


def _error_message(exc: Exception) -> str:
    return "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


@login_required
def config_index(request: HttpRequest) -> HttpResponse:
    return render(request, "logistics/config_index.html", {})


@login_required
def config_packaging_types(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

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

    packaging_types = LogPackagingType.objects.filter(tenant=tenant, is_active=True).order_by(
        "code"
    )
    return render(
        request,
        "logistics/config_packaging_types.html",
        {"packaging_types": packaging_types, "error": error},
    )


@login_required
def config_service_providers(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

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

    providers = LogServiceProvider.objects.filter(tenant=tenant, is_active=True).order_by("name")
    tariffs = LogFreightTariff.objects.filter(tenant=tenant, is_active=True).select_related(
        "provider"
    )
    return render(
        request,
        "logistics/config_service_providers.html",
        {
            "providers": providers,
            "tariffs": tariffs,
            "type_choices": LogServiceProvider.TYPE_CHOICES,
            "error": error,
        },
    )


@login_required
def config_hs_codes(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

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

    hs_codes = LogHsCode.objects.filter(tenant=tenant, is_active=True).order_by("code")
    return render(request, "logistics/config_hs_codes.html", {"hs_codes": hs_codes, "error": error})
