"""Ecrans de configuration/master-data du module `catalog` (U6),
regroupes sous le hub "Parametres" — meme patron que
`apps.accounting.views_config` : une seule page liste+creation par entite
simple, formulaire plain HTML, pas d'API ninja."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.catalog.models import (
    Attribute,
    AttributeValue,
    CatalogCertification,
    CatalogMaterialReference,
    CatalogStandard,
    Category,
    Packaging,
    PriceList,
    PriceListItem,
    ProductVariant,
    UnitConversion,
    UnitOfMeasure,
)
from apps.catalog.services.material_reference import set_attribute_value_color_reference
from apps.core.views.tenant_web import resolve_tenant


@login_required
def config_index(request: HttpRequest) -> HttpResponse:
    return render(request, "catalog/config_index.html", {})


@login_required
def config_categories(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    categories = Category.objects.filter(tenant=tenant, is_active=True)
    error = None

    if request.method == "POST":
        try:
            parent_id = request.POST.get("parent_id") or None
            parent = categories.get(id=parent_id) if parent_id else None
            Category.objects.create(
                tenant=tenant,
                name=request.POST.get("name", ""),
                parent=parent,
            )
        except Category.DoesNotExist:
            error = _("Categorie parente introuvable.")
        except (ValidationError, IntegrityError) as exc:
            error = str(exc)

    categories = Category.objects.filter(tenant=tenant, is_active=True).order_by("name")
    return render(
        request,
        "catalog/config_categories.html",
        {"categories": categories, "error": error},
    )


@login_required
def config_attributes(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            action = request.POST.get("action")
            if action == "add_value":
                attribute = Attribute.objects.get(
                    id=request.POST.get("attribute_id"), tenant=tenant
                )
                value = AttributeValue.objects.create(
                    tenant=tenant,
                    attribute=attribute,
                    value=request.POST.get("value", ""),
                )
                # REF1 (enrichissement referentiel LIFE MDG) : format de
                # reference Pantone optionnel, jamais de valeur
                # proprietaire chargee (cf. services/material_reference.py).
                pantone_code = request.POST.get("pantone_code", "")
                hex_approximation = request.POST.get("hex_approximation", "")
                if pantone_code or hex_approximation:
                    set_attribute_value_color_reference(
                        value,
                        pantone_code=pantone_code,
                        hex_approximation=hex_approximation,
                    )
            else:
                Attribute.objects.create(tenant=tenant, name=request.POST.get("name", ""))
        except Attribute.DoesNotExist:
            error = _("Attribut introuvable.")
        except (ValidationError, IntegrityError) as exc:
            error = str(exc)

    attributes = Attribute.objects.filter(tenant=tenant, is_active=True).prefetch_related("values")
    return render(
        request,
        "catalog/config_attributes.html",
        {"attributes": attributes, "error": error},
    )


@login_required
def config_uom(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    uoms = UnitOfMeasure.objects.filter(tenant=tenant, is_active=True)
    error = None

    if request.method == "POST":
        try:
            action = request.POST.get("action")
            if action == "add_conversion":
                from_unit = uoms.get(id=request.POST.get("from_unit_id"))
                to_unit = uoms.get(id=request.POST.get("to_unit_id"))
                UnitConversion.objects.create(
                    tenant=tenant,
                    from_unit=from_unit,
                    to_unit=to_unit,
                    factor=Decimal(request.POST.get("factor") or "0"),
                )
            else:
                UnitOfMeasure.objects.create(
                    tenant=tenant,
                    code=request.POST.get("code", ""),
                    name=request.POST.get("name", ""),
                    category=request.POST.get("category", UnitOfMeasure.CATEGORY_COUNT),
                    is_base=bool(request.POST.get("is_base")),
                )
        except UnitOfMeasure.DoesNotExist:
            error = _("Unite introuvable.")
        except (ValidationError, ValueError, InvalidOperation, IntegrityError) as exc:
            error = str(exc)

    uoms = UnitOfMeasure.objects.filter(tenant=tenant, is_active=True).order_by("code")
    conversions = UnitConversion.objects.filter(tenant=tenant).select_related(
        "from_unit", "to_unit"
    )
    return render(
        request,
        "catalog/config_uom.html",
        {
            "uoms": uoms,
            "conversions": conversions,
            "category_choices": UnitOfMeasure.CATEGORY_CHOICES,
            "error": error,
        },
    )


@login_required
def config_price_lists(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            PriceList.objects.create(
                tenant=tenant,
                name=request.POST.get("name", ""),
                kind=request.POST.get("kind", PriceList.KIND_DEFAULT),
                partner_id=request.POST.get("partner_id") or None,
                valid_from=(
                    date.fromisoformat(request.POST["valid_from"])
                    if request.POST.get("valid_from")
                    else None
                ),
                valid_to=(
                    date.fromisoformat(request.POST["valid_to"])
                    if request.POST.get("valid_to")
                    else None
                ),
            )
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    price_lists = PriceList.objects.filter(tenant=tenant, is_active=True).order_by("name")
    return render(
        request,
        "catalog/config_price_lists.html",
        {"price_lists": price_lists, "kind_choices": PriceList.KIND_CHOICES, "error": error},
    )


@login_required
def price_list_detail(request: HttpRequest, price_list_id: str) -> HttpResponse:
    tenant = resolve_tenant(request)
    price_list = get_object_or_404(PriceList, id=price_list_id, tenant=tenant)
    error = None

    if request.method == "POST":
        try:
            variant = ProductVariant.objects.get(id=request.POST.get("variant_id"), tenant=tenant)
            PriceListItem.objects.create(
                tenant=tenant,
                price_list=price_list,
                variant=variant,
                price_mga=Decimal(request.POST.get("price_mga") or "0"),
            )
        except ProductVariant.DoesNotExist:
            error = _("Variante introuvable.")
        except (ValidationError, InvalidOperation, IntegrityError) as exc:
            error = str(exc)
        else:
            return redirect("catalog:price_list_detail", price_list_id=price_list.id)

    items = price_list.items.select_related("variant", "variant__template")
    variants = ProductVariant.objects.filter(tenant=tenant, is_active=True)
    return render(
        request,
        "catalog/price_list_detail.html",
        {"price_list": price_list, "items": items, "variants": variants, "error": error},
    )


@login_required
def config_packaging(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    variants = ProductVariant.objects.filter(tenant=tenant, is_active=True)
    uoms = UnitOfMeasure.objects.filter(tenant=tenant, is_active=True)
    error = None

    if request.method == "POST":
        try:
            variant = variants.get(id=request.POST.get("variant_id"))
            uom = uoms.get(id=request.POST.get("uom_id"))
            Packaging.objects.create(
                tenant=tenant,
                variant=variant,
                unit_count=int(request.POST.get("unit_count") or 1),
                uom=uom,
                barcode=request.POST.get("barcode", ""),
            )
        except (ProductVariant.DoesNotExist, UnitOfMeasure.DoesNotExist):
            error = _("Variante ou unite introuvable.")
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    packagings = Packaging.objects.filter(tenant=tenant, is_active=True).select_related(
        "variant", "uom"
    )
    return render(
        request,
        "catalog/config_packaging.html",
        {"packagings": packagings, "variants": variants, "uoms": uoms, "error": error},
    )


@login_required
def config_standards(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            CatalogStandard.objects.create(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                description=request.POST.get("description", ""),
            )
        except (ValidationError, IntegrityError) as exc:
            error = str(exc)

    standards = CatalogStandard.objects.filter(tenant=tenant, is_active=True).order_by("code")
    return render(
        request,
        "catalog/config_standards.html",
        {"standards": standards, "error": error},
    )


@login_required
def config_certifications(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    variants = ProductVariant.objects.filter(tenant=tenant, is_active=True)
    standards = CatalogStandard.objects.filter(tenant=tenant, is_active=True)
    error = None

    if request.method == "POST":
        try:
            variant = variants.get(id=request.POST.get("variant_id"))
            standard = standards.get(id=request.POST.get("standard_id"))
            CatalogCertification.objects.create(
                tenant=tenant,
                variant=variant,
                standard=standard,
                partner_id=request.POST.get("partner_id") or None,
                valid_from=(
                    date.fromisoformat(request.POST["valid_from"])
                    if request.POST.get("valid_from")
                    else None
                ),
                valid_until=(
                    date.fromisoformat(request.POST["valid_until"])
                    if request.POST.get("valid_until")
                    else None
                ),
            )
        except (ProductVariant.DoesNotExist, CatalogStandard.DoesNotExist):
            error = _("Variante ou norme introuvable.")
        except (ValidationError, ValueError, IntegrityError) as exc:
            error = str(exc)

    certifications = CatalogCertification.objects.filter(
        tenant=tenant, is_active=True
    ).select_related("variant", "standard")
    return render(
        request,
        "catalog/config_certifications.html",
        {
            "certifications": certifications,
            "variants": variants,
            "standards": standards,
            "error": error,
        },
    )


@login_required
def config_material_references(request: HttpRequest) -> HttpResponse:
    """REF1 (enrichissement referentiel LIFE MDG, cf. plan) : referentiel
    de matieres fibres/tissus reutilisable (coton, PES, Nomex, Kevlar...),
    utilisable comme liste de reference dans la fiche variante (texte
    libre `TextileSpec.material`, aucune FK — cf. docstring
    `CatalogMaterialReference`). Meme patron qu'un `config_standards`."""
    tenant = resolve_tenant(request)
    error = None

    if request.method == "POST":
        try:
            CatalogMaterialReference.objects.create(
                tenant=tenant,
                code=request.POST.get("code", ""),
                name=request.POST.get("name", ""),
                nature=request.POST.get("nature", ""),
                typical_gsm_min=request.POST.get("typical_gsm_min") or None,
                typical_gsm_max=request.POST.get("typical_gsm_max") or None,
                usage_notes=request.POST.get("usage_notes", ""),
                supplier_reference=request.POST.get("supplier_reference", ""),
            )
        except (ValidationError, InvalidOperation, IntegrityError) as exc:
            error = str(exc)

    materials = CatalogMaterialReference.objects.filter(tenant=tenant, is_active=True).order_by(
        "code"
    )
    return render(
        request,
        "catalog/config_material_references.html",
        {
            "materials": materials,
            "nature_choices": CatalogMaterialReference.NATURE_CHOICES,
            "error": error,
        },
    )
