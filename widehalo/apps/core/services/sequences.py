from __future__ import annotations

from django.db import transaction

from apps.core.models.sequence import Sequence
from apps.core.models.tenant import Tenant


def next_reference(tenant: Tenant, code: str, fiscal_year: int) -> str:
    """Genere la prochaine reference sequencee pour (tenant, code, exercice),
    verrouillee en transaction pour eviter toute collision concurrente."""
    with transaction.atomic():
        sequence, _created = Sequence.objects.select_for_update().get_or_create(
            tenant=tenant, code=code, fiscal_year=fiscal_year
        )
        sequence.last_number += 1
        sequence.save(update_fields=["last_number"])
        return f"{code}-{fiscal_year}-{sequence.last_number:04d}"
