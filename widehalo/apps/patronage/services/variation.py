"""PAT-CPQ1 (enrichissement WideHalo) : le patron validé devient la source
de verite du futur configurateur commercial CPQ (`sales`/`crm`, differe) —
il expose ses points de variation (tailles, matieres admissibles) via
`services/public.py`."""

from __future__ import annotations

from typing import Any

from apps.patronage.models import PatPattern


def variation_points(pattern: PatPattern) -> dict[str, Any]:
    return {
        "sizes": list(pattern.size_chart.sizes),
        "material_variant_ids": sorted(
            {
                str(v)
                for v in pattern.pieces.exclude(material_variant_id__isnull=True).values_list(
                    "material_variant_id", flat=True
                )
            }
        ),
    }
