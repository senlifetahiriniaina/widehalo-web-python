"""Patrons et pieces (§5.4.2-5.4.3, RG-PAT-3/RG-PAT-6). Gabarits
parametriques SIMPLES pour chemise/pantalon/jupe/t-shirt — rectangles
dimensionnes a partir des points de mesure gradues, explicitement PAS un
rendu de patronage professionnel (le CDC precise que ce module n'est pas
un logiciel de CAO)."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.models.tenant import Tenant
from apps.patronage.models import PatPattern, PatPatternPiece, PatPieceGeometry, PatSizeChart

# Aisance de couture ajoutee par defaut aux gabarits parametriques.
DEFAULT_EASE_CM = Decimal("2")

# Points de mesure requis par type de piece, pour les 4 types de vetement
# couverts par les gabarits simples (chemise/tshirt/pantalon/jupe).
_PIECE_REQUIREMENTS: dict[str, tuple[str, str, str]] = {
    PatSizeChart.GARMENT_SHIRT: ("devant", "tour_poitrine", "longueur"),
    PatSizeChart.GARMENT_TSHIRT: ("devant", "tour_poitrine", "longueur"),
    PatSizeChart.GARMENT_PANTS: ("devant", "tour_taille", "longueur"),
    PatSizeChart.GARMENT_SKIRT: ("devant", "tour_taille", "longueur"),
}


def create_pattern(
    *,
    tenant: Tenant,
    code: str,
    name: str,
    size_chart: PatSizeChart,
    product_template_id: UUID | None = None,
) -> PatPattern:
    return PatPattern.objects.create(
        tenant=tenant,
        code=code,
        name=name,
        size_chart=size_chart,
        product_template_id=product_template_id,
        date_created=timezone.now().date(),
    )


def add_pattern_piece(
    pattern: PatPattern,
    *,
    code: str,
    name: str,
    qty_per_garment: int = 1,
    material_variant_id: UUID | None = None,
    seam_allowance_mm: Decimal = Decimal(10),
    is_lining: bool = False,
    notes: str = "",
) -> PatPatternPiece:
    if pattern.state != PatPattern.STATE_DRAFT:
        raise ValidationError(_("Un patron valide est fige — creer une nouvelle version."))

    return PatPatternPiece.objects.create(
        tenant=pattern.tenant,
        pattern=pattern,
        code=code,
        name=name,
        qty_per_garment=qty_per_garment,
        material_variant_id=material_variant_id,
        seam_allowance_mm=seam_allowance_mm,
        is_lining=is_lining,
        notes=notes,
    )


def validate_pattern(pattern: PatPattern) -> PatPattern:
    pattern.state = PatPattern.STATE_VALIDATED
    pattern.save(update_fields=["state"])
    return pattern


def new_pattern_version(pattern: PatPattern) -> PatPattern:
    """RG-PAT-6 : copie les pieces (pas la geometrie ni les mesures,
    recalculees pour la nouvelle version) dans un brouillon."""
    new_pattern = PatPattern.objects.create(
        tenant=pattern.tenant,
        code=pattern.code,
        name=pattern.name,
        product_template_id=pattern.product_template_id,
        size_chart=pattern.size_chart,
        version=pattern.version + 1,
        state=PatPattern.STATE_DRAFT,
        designer=pattern.designer,
        season=pattern.season,
        collection=pattern.collection,
        date_created=timezone.now().date(),
        notes=pattern.notes,
        parent_pattern=pattern,
    )
    for piece in pattern.pieces.all():
        PatPatternPiece.objects.create(
            tenant=piece.tenant,
            pattern=new_pattern,
            code=piece.code,
            name=piece.name,
            qty_per_garment=piece.qty_per_garment,
            material_variant_id=piece.material_variant_id,
            grain_direction=piece.grain_direction,
            seam_allowance_mm=piece.seam_allowance_mm,
            is_lining=piece.is_lining,
            is_interfacing=piece.is_interfacing,
            symmetry=piece.symmetry,
            notes=piece.notes,
        )
    return new_pattern


def _rectangle_geometry(width_cm: Decimal, height_cm: Decimal) -> dict[str, object]:
    points = [
        [0, 0],
        [float(width_cm), 0],
        [float(width_cm), float(height_cm)],
        [0, float(height_cm)],
    ]
    svg_path = f"M0,0 L{width_cm},0 L{width_cm},{height_cm} L0,{height_cm} Z"
    return {
        "points": points,
        "svg_path": svg_path,
        "area_cm2": width_cm * height_cm,
        "perimeter_cm": (width_cm + height_cm) * Decimal(2),
        "bounding_box": {"width": str(width_cm), "height": str(height_cm)},
    }


def generate_piece_geometry(
    piece: PatPatternPiece, *, size: str, graded_measurements: dict[str, Decimal]
) -> PatPieceGeometry:
    """Genere une geometrie rectangulaire simple, dimensionnee a partir des
    mesures gradees (cf. `services/grading.py::apply_grading`) pour la
    taille donnee — gabarit parametrique, pas une CAO."""
    garment_type = piece.pattern.size_chart.garment_type
    requirement = _PIECE_REQUIREMENTS.get(garment_type)
    if requirement is None:
        raise ValidationError(
            _(
                "Aucun gabarit parametrique disponible pour ce type de vetement — "
                "utiliser l'editeur de croquis manuel ou l'import SVG."
            )
        )
    _expected_piece_code, width_point, length_point = requirement

    if width_point not in graded_measurements or length_point not in graded_measurements:
        raise ValidationError(_("Points de mesure manquants pour generer le gabarit parametrique."))

    width = graded_measurements[width_point] / Decimal(4) + DEFAULT_EASE_CM
    height = graded_measurements[length_point]

    geometry_data = _rectangle_geometry(width, height)
    geometry, _created = PatPieceGeometry.objects.update_or_create(
        tenant=piece.tenant, piece=piece, size=size, defaults=geometry_data
    )
    return geometry
