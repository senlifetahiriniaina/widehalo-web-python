"""REF1 (enrichissement referentiel LIFE MDG) : la commande
`load_material_references` charge le referentiel de matieres fibres/tissus
et est idempotente (rejouee deux fois, ne cree pas de doublon par code)."""

from __future__ import annotations

import pytest
from django.core.management import call_command

from apps.catalog.models import CatalogMaterialReference
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db

_EXPECTED_CODES = {
    "COTON",
    "PES",
    "POLYCOTON",
    "MODACRYLIQUE",
    "NOMEX",
    "KEVLAR",
    "LAINE",
    "SOIE",
    "LIN",
    "NEOPRENE",
    "GORETEX",
    "MESH",
    "MOLLETON",
    "DENIM",
}


def test_load_material_references_creates_indicative_fixture_rows() -> None:
    tenant = Tenant.objects.create(code="CAT-MATCMD1", name="Material Command Tenant 1")
    call_command("load_material_references", tenant=tenant.code)
    with use_tenant(tenant.id):
        codes = set(
            CatalogMaterialReference.objects.filter(tenant=tenant).values_list("code", flat=True)
        )
        assert codes == _EXPECTED_CODES


def test_load_material_references_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="CAT-MATCMD2", name="Material Command Tenant 2")
    call_command("load_material_references", tenant=tenant.code)
    call_command("load_material_references", tenant=tenant.code)
    with use_tenant(tenant.id):
        assert CatalogMaterialReference.objects.filter(tenant=tenant).count() == len(
            _EXPECTED_CODES
        )
