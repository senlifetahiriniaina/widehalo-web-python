from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.catalog.models import (
    Attribute,
    CatalogSectorSpec,
    Category,
    PriceListItem,
    ProductSupplierInfo,
    ProductTemplate,
    ProductVariant,
    UnitOfMeasure,
)
from apps.catalog.services.sector_specs import create_sector_spec
from apps.catalog.services.variants import generate_variants, set_variant_attributes
from apps.core.views.smart_table import Column, smart_table_response
from apps.core.views.tenant_web import resolve_tenant

COLUMNS = [
    Column(key="reference", label="Reference"),
    Column(key="name", label="Nom"),
    Column(key="base_price_mga", label="Prix catalogue (MGA)", searchable=False),
    Column(key="is_sellable", label="Vendable", searchable=False),
]


@login_required
def template_list(request: HttpRequest) -> HttpResponse:
    queryset = ProductTemplate.objects.filter(is_active=True)
    return smart_table_response(
        request,
        table_key="catalog.templates",
        columns=COLUMNS,
        queryset=queryset,
        page_template="catalog/templates_list.html",
        page_context={"row_url_name": "catalog:template_detail"},
    )


def _category_label(category: Category) -> str:
    """Le catalogue est organise en famille (categorie racine) / sous-
    famille (categorie enfant, cf. `Category.parent` deja generique) —
    chaque produit cree DOIT etre range dans une sous-famille (jamais
    directement sous une famille racine), donc le selecteur du formulaire
    de creation n'affiche que les categories qui ONT un parent, avec le
    libelle complet "Famille > Sous-famille" pour lever toute ambiguite."""
    if category.parent_id:
        return f"{category.parent.name} > {category.name}"
    return category.name


@login_required
def template_create(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    subfamilies = (
        Category.objects.filter(tenant=tenant, is_active=True, parent__isnull=False)
        .select_related("parent")
        .order_by("parent__name", "name")
    )
    uoms = UnitOfMeasure.objects.filter(tenant=tenant, is_active=True).order_by("code")
    error = None

    if request.method == "POST":
        try:
            category = subfamilies.get(id=request.POST.get("category_id"))
            base_uom = uoms.get(id=request.POST.get("base_uom_id"))
            template = ProductTemplate.objects.create(
                tenant=tenant,
                name=request.POST.get("name", ""),
                category=category,
                base_uom=base_uom,
                base_price_mga=request.POST.get("base_price_mga") or 0,
                is_sellable=bool(request.POST.get("is_sellable")),
            )
        except Category.DoesNotExist:
            error = _(
                "Sous-famille introuvable — chaque produit doit être rangé "
                "dans une sous-famille du catalogue (créez-en une depuis "
                "Paramètres > Catégories si nécessaire)."
            )
        except UnitOfMeasure.DoesNotExist:
            error = _("Unité de base introuvable.")
        except (ValidationError, ValueError) as exc:
            error = str(exc)
        else:
            return redirect("catalog:template_detail", template_id=template.id)

    return render(
        request,
        "catalog/template_create.html",
        {
            "subfamilies": [(c, _category_label(c)) for c in subfamilies],
            "uoms": uoms,
            "error": error,
        },
    )


@login_required
def template_detail(request: HttpRequest, template_id: str) -> HttpResponse:
    template = get_object_or_404(ProductTemplate, id=template_id)
    error = None

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "toggle_sellable":
                template.is_sellable = not template.is_sellable
                template.save(update_fields=["is_sellable"])
            elif action == "generate_variants":
                attribute_ids = request.POST.getlist("attribute_ids")
                set_variant_attributes(template, attribute_ids)
                generate_variants(template)
            elif action == "add_supplier_info":
                variant = template.variants.get(id=request.POST.get("variant_id"))
                ProductSupplierInfo.objects.create(
                    tenant=template.tenant,
                    variant=variant,
                    partner_id=request.POST.get("partner_id"),
                    supplier_reference=request.POST.get("supplier_reference", ""),
                    price_mga=request.POST.get("price_mga") or 0,
                    lead_time_days=request.POST.get("lead_time_days") or 0,
                )
            elif action == "add_sector_spec":
                # SEC1 (extension sectorielle Madagascar) : fiche
                # sectorielle cuir/agroalimentaire/artisanat rattachee a
                # la fiche variante deja existante (U6) — jamais
                # import_export (cf. services/sector_specs.py).
                variant = template.variants.get(id=request.POST.get("variant_id"))
                try:
                    attributes = json.loads(request.POST.get("attributes") or "{}")
                except ValueError as exc:
                    raise ValidationError(_("Attributs JSON invalides.")) from exc
                create_sector_spec(
                    variant,
                    sector_code=request.POST.get("sector_code", ""),
                    attributes=attributes,
                )
        except (ValidationError, ValueError, ProductVariant.DoesNotExist) as exc:
            error = str(exc)
        else:
            return redirect("catalog:template_detail", template_id=template.id)

    variants = template.variants.filter(is_active=True).prefetch_related(
        "attribute_values", "textile_spec", "sector_spec", "supplier_infos"
    )
    price_items = PriceListItem.objects.filter(variant__template=template).select_related(
        "price_list", "variant"
    )
    attributes = Attribute.objects.all()

    return render(
        request,
        "catalog/template_detail.html",
        {
            "template": template,
            "variants": variants,
            "price_items": price_items,
            "attributes": attributes,
            "current_attribute_ids": {a.id for a in template.variant_attributes.all()},
            "sector_choices": CatalogSectorSpec.SECTOR_CHOICES,
            "error": error,
        },
    )


@login_required
def textile_converter(request: HttpRequest) -> HttpResponse:
    """Calculatrice autonome poids <-> longueur pour un tissu (grammage +
    laize), sans modele persiste — cf. `services/textile.py`."""
    from decimal import Decimal, InvalidOperation

    from apps.catalog.models import TextileSpec
    from apps.catalog.services.textile import length_from_weight_kg, weight_kg_from_length

    result = None
    error = None

    if request.method == "POST":
        try:
            spec = TextileSpec(
                weight_gsm=Decimal(request.POST.get("weight_gsm") or "0"),
                width_cm=Decimal(request.POST.get("width_cm") or "0"),
            )
            direction = request.POST.get("direction")
            if direction == "weight_to_length":
                result = length_from_weight_kg(spec, Decimal(request.POST.get("weight_kg") or "0"))
            else:
                result = weight_kg_from_length(spec, Decimal(request.POST.get("length_m") or "0"))
        except (ValidationError, InvalidOperation, ValueError) as exc:
            error = str(exc)

    return render(
        request,
        "catalog/textile_converter.html",
        {"result": result, "error": error},
    )
