from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from ninja import File, Router, Schema
from ninja.files import UploadedFile

from apps.catalog.models import (
    AttributeValue,
    CatalogCustomizationOption,
    CatalogMaterialReference,
    Category,
    ProductTemplate,
    ProductVariant,
    UnitOfMeasure,
)
from apps.catalog.services.catalog_import import import_catalog_xlsx
from apps.catalog.services.material_reference import set_attribute_value_color_reference
from apps.catalog.services.pricing import get_price
from apps.catalog.services.sector_specs import create_sector_spec
from apps.catalog.services.variants import generate_variants, set_variant_attributes
from apps.core.services.permissions import require_permission

router = Router(tags=["catalog"])


class TemplateIn(Schema):
    name: str
    base_uom_id: str
    category_id: str | None = None
    base_price_mga: Decimal = Decimal(0)
    is_sellable: bool = True


class TemplateSellableIn(Schema):
    is_sellable: bool


class VariantAttributesIn(Schema):
    attribute_ids: list[str]


class SectorSpecIn(Schema):
    sector_code: str
    attributes: dict


class ColorReferenceIn(Schema):
    """REF1 (enrichissement referentiel LIFE MDG) : `pantone_code` valide
    par `services/material_reference.py` (format `NN-NNNN TCX`, jamais de
    valeur Pantone proprietaire), `hex_approximation` toujours saisie
    manuellement par l'utilisateur."""

    pantone_code: str = ""
    hex_approximation: str = ""


def _serialize_template(template: ProductTemplate) -> dict:
    return {
        "id": str(template.id),
        "reference": template.reference,
        "name": template.name,
        "base_price_mga": str(template.base_price_mga),
        "is_sellable": template.is_sellable,
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
        is_sellable=payload.is_sellable,
    )
    return _serialize_template(template)


@router.post("/catalog/templates/{template_id}/sellable")
@require_permission("catalog.change_producttemplate")
def set_template_sellable(request, template_id: str, payload: TemplateSellableIn):
    template = get_object_or_404(ProductTemplate, id=template_id)
    template.is_sellable = payload.is_sellable
    template.save(update_fields=["is_sellable"])
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


@router.post("/catalog/variants/{variant_id}/sector-spec")
@require_permission("catalog.add_catalogsectorspec")
def create_sector_spec_endpoint(request, variant_id: str, payload: SectorSpecIn):
    """SEC1 (extension sectorielle Madagascar) : cree la fiche sectorielle
    (cuir/agroalimentaire/artisanat, jamais import_export — cf.
    `services/sector_specs.py`) d'une variante deja existante."""
    variant = get_object_or_404(ProductVariant, id=variant_id)
    try:
        spec = create_sector_spec(
            variant, sector_code=payload.sector_code, attributes=payload.attributes
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {
        "id": str(spec.id),
        "sector_code": spec.sector_code,
        "attributes": spec.attributes,
    }


@router.get("/catalog/material-references")
@require_permission("catalog.view_catalogmaterialreference")
def list_material_references(request):
    """REF1 (enrichissement referentiel LIFE MDG) : referentiel de matieres
    fibres/tissus reutilisable (~14 entrees fixture, cf.
    `fixtures/materials_reference_mg.json`), utilise pour peupler une liste
    de selection dans la fiche variante (aucune FK — cf. docstring
    `CatalogMaterialReference`)."""
    return {
        "results": [
            {
                "id": str(m.id),
                "code": m.code,
                "name": m.name,
                "nature": m.nature,
                "typical_gsm_min": str(m.typical_gsm_min) if m.typical_gsm_min else None,
                "typical_gsm_max": str(m.typical_gsm_max) if m.typical_gsm_max else None,
            }
            for m in CatalogMaterialReference.objects.filter(is_active=True).order_by("code")
        ]
    }


@router.post("/catalog/attribute-values/{attribute_value_id}/color-reference")
@require_permission("catalog.change_attributevalue")
def set_color_reference_endpoint(request, attribute_value_id: str, payload: ColorReferenceIn):
    """REF1 (enrichissement referentiel LIFE MDG) : fixe le format de
    reference Pantone (`pantone_code`, `NN-NNNN TCX`) et l'approximation
    hex manuelle d'une `AttributeValue` de couleur — reserve legale
    explicite, cf. `services/material_reference.py`."""
    attribute_value = get_object_or_404(AttributeValue, id=attribute_value_id)
    try:
        updated = set_attribute_value_color_reference(
            attribute_value,
            pantone_code=payload.pantone_code,
            hex_approximation=payload.hex_approximation,
        )
    except ValidationError as exc:
        return JsonResponse({"detail": "; ".join(exc.messages)}, status=400)
    return {
        "id": str(updated.id),
        "pantone_code": updated.pantone_code,
        "hex_approximation": updated.hex_approximation,
    }


@router.get("/catalog/customization-options")
@require_permission("catalog.view_catalogcustomizationoption")
def list_customization_options(request, material_id: str = ""):
    """REF2 (enrichissement referentiel LIFE MDG) : liste les options de
    personnalisation (~7 techniques fixture, cf.
    `fixtures/customization_options.json`) — filtrable par
    `material_id` (`CatalogMaterialReference.id`) pour n'afficher QUE les
    options connues compatibles avec cette matiere (ex. la gravure,
    reservee au cuir/metal, disparait de la liste filtree par une matiere
    textile — cf. scenario manuel de fin de chantier, plan REF)."""
    queryset = CatalogCustomizationOption.objects.filter(is_active=True)
    if material_id:
        queryset = queryset.filter(compatible_materials__id=material_id)
    return {
        "results": [
            {
                "id": str(o.id),
                "code": o.code,
                "name": o.name,
                "technique": o.technique,
                "compatible_material_codes": [m.code for m in o.compatible_materials.all()],
            }
            for o in queryset.distinct().order_by("code")
        ]
    }


@router.get("/catalog/variants/{variant_id}/price")
@require_permission("catalog.view_productvariant")
def variant_price_endpoint(request, variant_id: str, partner_id: str = ""):
    variant = get_object_or_404(ProductVariant, id=variant_id)
    price = get_price(variant, partner_id=partner_id or None)
    return {"price_mga": str(price)}


# ---------------------------------------------------------------------------
# Import catalogue depuis Excel (cf. docs/IMPORT_FORMATS.md)
# ---------------------------------------------------------------------------


@router.post("/catalog/imports/catalog")
@require_permission("catalog.add_producttemplate")
def import_catalog_endpoint(
    request,
    file: UploadedFile = File(...),  # noqa: B008 — idiome django-ninja standard
):
    """Import xlsx du catalogue (gammes + variantes generees + specs
    textiles) — cf. docstring de `services/catalog_import.py`/
    `docs/IMPORT_FORMATS.md`. Meme idiome multipart que
    `accounting.import_chart_of_accounts_endpoint`."""
    from apps.core.models.tenant import Tenant

    tenant = Tenant.objects.get(id=request.headers.get("X-Tenant-Id"))
    try:
        summary = import_catalog_xlsx(tenant, file.read(), filename=file.name)
    except ValueError as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return {
        "is_valid": summary.is_valid,
        "total_rows": summary.total_rows,
        "created_count": summary.created_count,
        "skipped_existing_count": summary.skipped_existing_count,
        "variants_created_count": summary.variants_created_count,
        "textile_specs_created_count": summary.textile_specs_created_count,
        "row_errors": [
            {"row_index": row_error.row_index, "errors": row_error.errors}
            for row_error in summary.row_errors
        ],
    }
