"""SEC2 (extension sectorielle Madagascar) : la commande
`load_sector_certifications` charge le referentiel de normes CAT-NORM1 pour
les secteurs cuir/agroalimentaire/artisanat et est idempotente (rejouee
deux fois, ne cree pas de doublon par code)."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.catalog.models import CatalogStandard
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_load_sector_certifications_creates_indicative_fixture_rows() -> None:
    tenant = Tenant.objects.create(code="CAT-CMD1", name="Command Tenant 1")
    call_command("load_sector_certifications", tenant=tenant.code)
    with use_tenant(tenant.id):
        codes = set(CatalogStandard.objects.filter(tenant=tenant).values_list("code", flat=True))
        assert codes == {"LWG-AUDIT", "HACCP", "BIO-MG", "LABEL-ARTISANAT-MG"}


def test_load_sector_certifications_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="CAT-CMD2", name="Command Tenant 2")
    call_command("load_sector_certifications", tenant=tenant.code)
    call_command("load_sector_certifications", tenant=tenant.code)
    with use_tenant(tenant.id):
        assert CatalogStandard.objects.filter(tenant=tenant).count() == 4
