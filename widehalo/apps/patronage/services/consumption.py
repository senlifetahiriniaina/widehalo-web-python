"""RG-PAT-4 (consommation matiere) et RG-PAT-5 (`push_to_bom`, point
d'integration central explicitement designe par le commanditaire —
traçable via `core.services.audit.log_action`, reversible en rappelant
`push_to_bom` avec un dictionnaire vide ou en revalidant depuis
`PatConsumption`)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.core.services.audit import log_action
from apps.mrp.services.public import set_bom_line_qty_by_size
from apps.patronage.models import PatConsumption, PatMarker, PatPattern


def compute_consumption(
    pattern: PatPattern,
    *,
    size: str,
    material_variant_id: UUID,
    width_cm: Decimal,
    waste_pct: Decimal = Decimal(0),
) -> PatConsumption:
    """Surface totale des pieces utilisant cette matiere x (1+chute) /
    laize (RG-PAT-4, mode `calcul`)."""
    total_area_cm2 = Decimal(0)
    for piece in pattern.pieces.filter(material_variant_id=material_variant_id):
        geometry = piece.geometries.filter(size=size).first()
        if geometry is None or geometry.area_cm2 is None:
            continue
        total_area_cm2 += geometry.area_cm2 * piece.qty_per_garment

    if not total_area_cm2:
        raise ValidationError(
            _("Aucune géométrie disponible pour cette matière/taille — générer les pièces d'abord.")
        )

    adjusted_area_cm2 = total_area_cm2 * (Decimal(1) + waste_pct / Decimal(100))
    length_cm = adjusted_area_cm2 / width_cm
    length_m = length_cm / Decimal(100)

    consumption, _created = PatConsumption.objects.update_or_create(
        tenant=pattern.tenant,
        pattern=pattern,
        size=size,
        material_variant_id=material_variant_id,
        defaults={
            "length_m": length_m,
            "width_cm": width_cm,
            "area_m2": total_area_cm2 / Decimal(10000),
            "waste_pct": waste_pct,
            "method": PatConsumption.METHOD_CALCULATION,
        },
    )
    return consumption


def compute_marker(
    pattern: PatPattern,
    *,
    material_variant_id: UUID,
    fabric_width_cm: Decimal,
    size_ratio: dict[str, int],
    efficiency_pct: Decimal = Decimal(85),
) -> PatMarker:
    """RG-PAT-4, mode `placement` : rendement d'un plan de coupe pour un
    ratio de tailles donne — plus precis qu'un calcul taille par taille
    isole, mais reste une approximation (pas un vrai algorithme de nesting
    2D, hors de portee de ce lot)."""
    total_area_cm2 = Decimal(0)
    for size, count in size_ratio.items():
        for piece in pattern.pieces.filter(material_variant_id=material_variant_id):
            geometry = piece.geometries.filter(size=size).first()
            if geometry is None or geometry.area_cm2 is None:
                continue
            total_area_cm2 += geometry.area_cm2 * piece.qty_per_garment * Decimal(count)

    if not total_area_cm2:
        raise ValidationError(
            _("Aucune géométrie disponible pour cette matière — générer les pièces d'abord.")
        )

    length_cm = total_area_cm2 / fabric_width_cm / (efficiency_pct / Decimal(100))
    length_m = length_cm / Decimal(100)

    marker = PatMarker.objects.create(
        tenant=pattern.tenant,
        pattern=pattern,
        fabric_width_cm=fabric_width_cm,
        size_ratio=size_ratio,
        length_m=length_m,
        efficiency_pct=efficiency_pct,
    )
    return marker


def push_to_bom(
    pattern: PatPattern, *, bom_id: UUID, material_variant_id: UUID, actor: User | None = None
) -> bool:
    """RG-PAT-5 : alimente `mrp_bom_line.qty_by_size` avec les metrages
    calcules par taille pour cette matiere. Traçable (journal d'audit) et
    reversible (rappeler avec un dictionnaire vide via `revert_push_to_bom`)."""
    qty_by_size = {
        c.size: c.length_m
        for c in PatConsumption.objects.filter(
            pattern=pattern, material_variant_id=material_variant_id
        )
    }
    if not qty_by_size:
        raise ValidationError(_("Aucune consommation calculée pour cette matière."))

    updated = set_bom_line_qty_by_size(
        bom_id=bom_id, component_variant_id=material_variant_id, qty_by_size=qty_by_size
    )
    log_action(
        "patronage.push_to_bom",
        actor=actor,
        obj=pattern,
        changes={"bom_id": str(bom_id), "material_variant_id": str(material_variant_id)},
        metadata={"qty_by_size": {k: str(v) for k, v in qty_by_size.items()}, "applied": updated},
    )
    return updated


def revert_push_to_bom(
    pattern: PatPattern, *, bom_id: UUID, material_variant_id: UUID, actor: User | None = None
) -> bool:
    """Reversibilite explicite de `push_to_bom` (RG-PAT-5) : remet
    `qty_by_size` a vide sur la ligne concernee."""
    updated = set_bom_line_qty_by_size(
        bom_id=bom_id, component_variant_id=material_variant_id, qty_by_size={}
    )
    log_action(
        "patronage.push_to_bom.revert",
        actor=actor,
        obj=pattern,
        changes={"bom_id": str(bom_id), "material_variant_id": str(material_variant_id)},
        metadata={"applied": updated},
    )
    return updated
