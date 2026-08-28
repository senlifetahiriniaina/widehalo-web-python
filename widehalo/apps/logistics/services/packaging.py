"""LOG3 : plan d'emballage (RG-LOG-5). Calculateur SIMPLIFIE, documente
comme tel : le poids/volume total du plan derive uniquement de la
capacite du CONTENANT (`LogPackagingType.tare_weight_kg`/`volume_m3`) —
le poids/volume propre du contenu (le produit lui-meme) n'est pas ajoute,
faute d'une donnee generique de poids unitaire exposee par `catalog` pour
tout type de produit (`TextileSpec` existe mais est specifique au textile,
pas un poids/volume unitaire universel). A affiner si un besoin reel de
precision se presente — documente explicitement plutot que devine."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db.models import Model
from django.utils.translation import gettext as _

from apps.catalog.services.public import get_variant_packaging
from apps.logistics.models import LogPackagingPlan, LogPackagingPlanLine, LogPackagingType

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant


def compute_packaging_plan(
    tenant: Tenant,
    *,
    source: Model,
    packaging_type: LogPackagingType,
    lines: list[dict[str, Any]],
) -> LogPackagingPlan:
    """`lines` : liste de dicts `{variant_id, qty}`. Pour chaque ligne, le
    conditionnement catalogue (`catalog.services.public.get_variant_packaging`)
    determine combien d'unites tiennent par colis (`unit_count`) — une
    variante sans conditionnement declare est refusee explicitement (jamais
    un colis "a l'unite" suppose silencieusement)."""
    if not lines:
        raise ValidationError(_("Un plan d'emballage doit comporter au moins une ligne."))

    from django.contrib.contenttypes.models import ContentType

    plan = LogPackagingPlan(
        tenant=tenant,
        content_type=ContentType.objects.get_for_model(source),
        object_id=source.pk,
    )
    plan.full_clean()
    plan.save()

    total_packages = 0
    for line_data in lines:
        variant_id = line_data["variant_id"]
        qty = Decimal(line_data["qty"])
        packaging_info = get_variant_packaging(variant_id)
        if packaging_info is None:
            raise ValidationError(
                _(
                    "Aucun conditionnement catalogue declare pour cette variante — "
                    "a renseigner avant de calculer un plan d'emballage."
                )
            )
        unit_count = packaging_info["unit_count"]
        qty_packages = math.ceil(qty / unit_count) if unit_count else 0

        line = LogPackagingPlanLine(
            tenant=tenant,
            plan=plan,
            packaging_type=packaging_type,
            variant_id=variant_id,
            qty_units=qty,
            qty_packages=qty_packages,
        )
        line.full_clean()
        line.save()
        total_packages += qty_packages

    plan.total_weight_kg = packaging_type.tare_weight_kg * total_packages
    plan.total_volume_m3 = (packaging_type.volume_m3 or Decimal(0)) * total_packages
    plan.save(update_fields=["total_weight_kg", "total_volume_m3"])
    return plan
