"""Referentiel de benchmarks sectoriels (`StgSectorBenchmark`, 5 secteurs) et
notes qualitatives (`StgNote`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import Q

from apps.strategy.models import StgNote, StgObjective, StgSectorBenchmark

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User


def get_benchmarks_for_sector(
    tenant: Tenant, sector_code: str, *, as_of: dt.date | None = None
) -> list[StgSectorBenchmark]:
    """Benchmarks EN VIGUEUR a une date donnee (par defaut aujourd'hui) —
    meme logique de versionnement par date d'effet que
    `core.RegulatoryParameter`."""
    as_of = as_of or dt.date.today()
    return list(
        StgSectorBenchmark.objects.filter(
            tenant=tenant, sector_code=sector_code, valid_from__lte=as_of
        )
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=as_of))
        .order_by("kpi_code")
    )


def create_sector_benchmark(
    tenant: Tenant,
    *,
    sector_code: str,
    kpi_code: str,
    kpi_label: str,
    valid_from: dt.date,
    target_min: Decimal | None = None,
    target_max: Decimal | None = None,
    unit: str = "",
    valid_to: dt.date | None = None,
) -> StgSectorBenchmark:
    benchmark = StgSectorBenchmark(
        tenant=tenant,
        sector_code=sector_code,
        kpi_code=kpi_code,
        kpi_label=kpi_label,
        target_min=target_min,
        target_max=target_max,
        unit=unit,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    benchmark.full_clean()
    benchmark.save()
    return benchmark


def create_note(
    tenant: Tenant,
    *,
    title: str,
    body: str = "",
    objective: StgObjective | None = None,
    author: User | None = None,
) -> StgNote:
    """`body` n'est jamais wrappe en `gettext` (contenu redige par un humain
    dans sa propre langue de travail, cf. docstring `models.py`)."""
    note = StgNote(tenant=tenant, title=title, body=body, objective=objective, author=author)
    note.full_clean()
    note.save()
    return note
