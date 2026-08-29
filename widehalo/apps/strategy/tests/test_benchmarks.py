from __future__ import annotations

import datetime

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.strategy.models import SECTOR_LEATHER, SECTOR_TEXTILE
from apps.strategy.services.benchmarks import (
    create_note,
    create_sector_benchmark,
    get_benchmarks_for_sector,
)

pytestmark = pytest.mark.django_db


def test_sector_benchmark_versioned_by_effective_date() -> None:
    tenant = Tenant.objects.create(code="STG-B1", name="Benchmark Tenant 1")
    with use_tenant(tenant.id):
        create_sector_benchmark(
            tenant,
            sector_code=SECTOR_TEXTILE,
            kpi_code="marge_brute_pct",
            kpi_label="Marge brute",
            valid_from=datetime.date(2020, 1, 1),
            valid_to=datetime.date(2024, 12, 31),
        )
        create_sector_benchmark(
            tenant,
            sector_code=SECTOR_TEXTILE,
            kpi_code="marge_brute_pct",
            kpi_label="Marge brute (revisee)",
            valid_from=datetime.date(2025, 1, 1),
        )
        current = get_benchmarks_for_sector(tenant, SECTOR_TEXTILE, as_of=datetime.date(2026, 1, 1))
        assert len(current) == 1
        assert current[0].kpi_label == "Marge brute (revisee)"

        historical = get_benchmarks_for_sector(
            tenant, SECTOR_TEXTILE, as_of=datetime.date(2022, 1, 1)
        )
        assert len(historical) == 1
        assert historical[0].kpi_label == "Marge brute"


def test_non_textile_sector_stays_empty_framework() -> None:
    """Decision actee : les 4 secteurs hors textile restent un cadre VIDE
    pour ce chantier (aucune fixture) — rempli lors de l'extension
    sectorielle Madagascar (cf. plan)."""
    tenant = Tenant.objects.create(code="STG-B2", name="Benchmark Tenant 2")
    with use_tenant(tenant.id):
        assert get_benchmarks_for_sector(tenant, SECTOR_LEATHER) == []


def test_create_note_body_is_free_text_not_gettext_wrapped() -> None:
    tenant = Tenant.objects.create(code="STG-B3", name="Benchmark Tenant 3")
    with use_tenant(tenant.id):
        note = create_note(tenant, title="Synthese T3", body="Contenu redige par la direction.")
        assert note.body == "Contenu redige par la direction."
        assert note.objective is None
