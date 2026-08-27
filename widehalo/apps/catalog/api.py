from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.catalog.models import Category, ProductTemplate, ProductVariant, UnitOfMeasure
from apps.catalog.services.pricing import get_price
from apps.catalog.services.variants import generate_variants, set_variant_attributes
from apps.core.services.permissions import require_permission

router = Router(tags=["catalog"])


class TemplateIn(Schema):
    name: str
    base_uom_id: str
    category_id: str | None = None
    base_price_mga: Decimal = Decimal(0)


class VariantAttributesIn(Schema):
    attribute_ids: list[str]


def _serialize_template(template: ProductTemplate) -> dict:
    return {
        "id": str(template.id),
        "reference": template.reference,
        "name": template.name,
        "base_price_mga": str(template.base_price_mga),
    }


def _serialize_variant(variant: ProductVariant) -> dict:
    return {
        "id": str(variant.id),
        "reference": variant.reference,
        "attribute_values": [str(v) for v in variant.attribute_values.all()],
    }


# NOTE ordre des decorateurs : `@router.xxx` DOIT etre le decorateur EXTERNE
# (le plus haut) et `@require_permission(...)` l'INTERNE (juste au-dessus de
# `def`). `Router.api_operation` enregistre dans `add_api_operation` la
# fonction qui lui est passee DIRECTEMENT, puis la retourne inchangee — donc
# seul le decorateur le plus proche de `def` finit dans la table de routage
# effectivement invoquee a chaque requete (verifie empiriquement).
@router.get("/catalog/templates")
@require_permission("catalog.view_producttemplate")
def list_templates(request):
    return {
        "results": [_serialize_template(t) for t in ProductTemplate.objects.filter(is_active=True)]
    }


@router.post("/catalog/templates")
@require_permission("catalog.add_producttemplate")
def create_template(request, payload: TemplateIn):
    base_uom = get_object_or_404(UnitOfMeasure, id=payload.base_uom_id)
    category = get_object_or_404(Category, id=payload.category_id) if payload.category_id else None
    template = ProductTemplate.objects.create(
        tenant=base_uom.tenant,
        name=payload.name,
        base_uom=base_uom,
        category=category,
        base_price_mga=payload.base_price_mga,
    )
    return _serialize_template(template)


@router.post("/catalog/templates/{template_id}/variant-attributes")
@require_permission("catalog.change_producttemplate")
def set_variant_attributes_endpoint(request, template_id: str, payload: VariantAttributesIn):
    template = get_object_or_404(ProductTemplate, id=template_id)
    try:
        set_variant_attributes(template, payload.attribute_ids)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {"status": "ok"}


@router.post("/catalog/templates/{template_id}/generate-variants")
@require_permission("catalog.add_productvariant")
def generate_variants_endpoint(request, template_id: str):
    template = get_object_or_404(ProductTemplate, id=template_id)
    try:
        variants = generate_variants(template)
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {"results": [_serialize_variant(v) for v in variants]}


@router.get("/catalog/variants/{variant_id}/price")
@require_permission("catalog.view_productvariant")
def variant_price_endpoint(request, variant_id: str, partner_id: str = ""):
    variant = get_object_or_404(ProductVariant, id=variant_id)
    price = get_price(variant, partner_id=partner_id or None)
    return {"price_mga": str(price)}
