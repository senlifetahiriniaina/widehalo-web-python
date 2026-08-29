from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.strategy.models import SECTOR_TEXTILE, StgSectorBenchmark

pytestmark = pytest.mark.django_db


def test_load_textile_benchmarks_command_creates_indicative_fixture_rows() -> None:
    tenant = Tenant.objects.create(code="STG-CMD1", name="Command Tenant 1")
    call_command("load_textile_benchmarks", tenant=tenant.code, valid_from="2026-01-01")
    with use_tenant(tenant.id):
        rows = StgSectorBenchmark.objects.filter(tenant=tenant, sector_code=SECTOR_TEXTILE)
        assert rows.count() == 5
