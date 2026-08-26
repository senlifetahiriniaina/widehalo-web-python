"""Nomenclatures (§5.3.3, RG-MRP-1 a 5) : multiniveaux avec detection de
cycle, consommation par taille, composants conditionnels, taux de chute,
versionnage (une nomenclature active est immuable, toute evolution cree
une nouvelle version)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.mrp.models import MrpBom, MrpBomLine, MrpOperation, MrpRouting

MAX_BOM_DEPTH = 5


def create_bom(
    *,
    tenant: Tenant,
    code: str,
    product_template_id: UUID,
    variant_id: UUID | None = None,
    type: str = MrpBom.TYPE_MANUFACTURE,
    qty: Decimal = Decimal(1),
    uom_code: str = "",
    routing: MrpRouting | None = None,
) -> MrpBom:
    return MrpBom.objects.create(
        tenant=tenant,
        code=code,
        product_template_id=product_template_id,
        variant_id=variant_id,
        type=type,
        qty=qty,
        uom_code=uom_code,
        routing=routing,
        version=1,
        effective_from=timezone.now().date(),
    )


def _check_no_cycle(root_template_id: UUID, component_template_id: UUID, depth: int) -> None:
    if depth > MAX_BOM_DEPTH:
        raise ValidationError(_("Profondeur de nomenclature maximale (5 niveaux) depassee."))
    if component_template_id == root_template_id:
        raise ValidationError(_("Cycle detecte dans la nomenclature."))

    child_bom = MrpBom.objects.filter(
        product_template_id=component_template_id, state=MrpBom.STATE_ACTIVE
    ).first()
    if child_bom is None:
        return
    for line in child_bom.lines.all():
        _check_no_cycle(root_template_id, line.component_template_id, depth + 1)


def add_bom_line(
    bom: MrpBom,
    *,
    component_template_id: UUID,
    component_variant_id: UUID | None = None,
    qty: Decimal = Decimal(1),
    uom_code: str = "",
    waste_pct: Decimal = Decimal(0),
    apply_on_attribute_values: list[str] | None = None,
    qty_by_size: dict[str, Any] | None = None,
    is_optional: bool = False,
    sequence: int = 0,
    operation: MrpOperation | None = None,
) -> MrpBomLine:
    if bom.state == MrpBom.STATE_ACTIVE:
        raise ValidationError(
            _("Une nomenclature active est immuable — creer une nouvelle version.")
        )

    _check_no_cycle(bom.product_template_id, component_template_id, depth=1)

    return MrpBomLine.objects.create(
        tenant=bom.tenant,
        bom=bom,
        sequence=sequence,
        component_template_id=component_template_id,
        component_variant_id=component_variant_id,
        qty=qty,
        uom_code=uom_code,
        waste_pct=waste_pct,
        apply_on_attribute_values=apply_on_attribute_values or [],
        qty_by_size=qty_by_size or {},
        is_optional=is_optional,
        operation=operation,
    )


def activate_bom(bom: MrpBom) -> MrpBom:
    """Rend cette version active et bascule toute version active precedente
    du meme produit en obsolete."""
    MrpBom.objects.filter(
        tenant=bom.tenant, product_template_id=bom.product_template_id, state=MrpBom.STATE_ACTIVE
    ).exclude(id=bom.id).update(state=MrpBom.STATE_OBSOLETE, effective_to=timezone.now().date())
    bom.state = MrpBom.STATE_ACTIVE
    bom.save(update_fields=["state"])
    return bom


def new_version(bom: MrpBom) -> MrpBom:
    """RG-MRP-5 : une nomenclature active ne se modifie pas — toute
    evolution cree une nouvelle version en brouillon, copie des lignes de la
    version courante. Les ordres de fabrication en cours conservent leur
    version (ils referencent le FK `bom` de la version d'origine, jamais
    modifiee)."""
    new_bom = MrpBom.objects.create(
        tenant=bom.tenant,
        code=bom.code,
        product_template_id=bom.product_template_id,
        variant_id=bom.variant_id,
        type=bom.type,
        qty=bom.qty,
        uom_code=bom.uom_code,
        routing=bom.routing,
        version=bom.version + 1,
        effective_from=timezone.now().date(),
        state=MrpBom.STATE_DRAFT,
        parent_bom=bom,
        notes=bom.notes,
    )
    for line in bom.lines.all():
        MrpBomLine.objects.create(
            tenant=line.tenant,
            bom=new_bom,
            sequence=line.sequence,
            component_template_id=line.component_template_id,
            component_variant_id=line.component_variant_id,
            qty=line.qty,
            uom_code=line.uom_code,
            waste_pct=line.waste_pct,
            apply_on_attribute_values=line.apply_on_attribute_values,
            qty_by_size=line.qty_by_size,
            is_optional=line.is_optional,
            operation=line.operation,
        )
    return new_bom


def explode(
    bom: MrpBom,
    qty: Decimal,
    *,
    size: str | None = None,
    attribute_values: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Eclatement multiniveau (RG-MRP-2/3/4) : retourne la liste a plat des
    composants a consommer, quantites planifiees deja majorees du taux de
    chute et resolues par taille a CHAQUE niveau (une sous-nomenclature peut
    avoir sa propre grille `qty_by_size`)."""
    results: list[dict[str, Any]] = []
    _explode_level(bom, qty, size, attribute_values or [], results, depth=1)
    return results


def _explode_level(
    bom: MrpBom,
    qty_needed: Decimal,
    size: str | None,
    attribute_values: list[str],
    results: list[dict[str, Any]],
    depth: int,
) -> None:
    if depth > MAX_BOM_DEPTH:
        raise ValidationError(_("Profondeur de nomenclature maximale (5 niveaux) depassee."))

    for line in bom.lines.all():
        if line.apply_on_attribute_values and not (
            set(line.apply_on_attribute_values) & set(attribute_values)
        ):
            continue

        base_qty = line.qty
        if size and line.qty_by_size and size in line.qty_by_size:
            base_qty = Decimal(str(line.qty_by_size[size]))

        planned_qty = base_qty * qty_needed * (Decimal(1) + line.waste_pct / Decimal(100))
        results.append(
            {
                "bom_line_id": line.id,
                "component_template_id": line.component_template_id,
                "component_variant_id": line.component_variant_id,
                "qty": planned_qty,
                "uom_code": line.uom_code,
            }
        )

        child_bom = MrpBom.objects.filter(
            product_template_id=line.component_template_id, state=MrpBom.STATE_ACTIVE
        ).first()
        if child_bom is not None:
            _explode_level(child_bom, planned_qty, size, attribute_values, results, depth + 1)
