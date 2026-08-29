"""REF2 (enrichissement referentiel LIFE MDG, cf. plan) :
`CatalogCustomizationOption`, chargement idempotent
(`load_customization_options`, `load_epi_standards`), et filtrage par
compatibilite matiere via l'API."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.test import Client

from apps.catalog.models import (
    CatalogCustomizationOption,
    CatalogStandard,
)
from apps.catalog.tests.factories import (
    CatalogCustomizationOptionFactory,
    CatalogMaterialReferenceFactory,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


def test_customization_option_str_shows_code_and_name() -> None:
    tenant = Tenant.objects.create(code="CAT-CUST1", name="Customization Tenant 1")
    with use_tenant(tenant.id):
        option = CatalogCustomizationOptionFactory(tenant=tenant, code="BRODERIE", name="Broderie")
        assert str(option) == "BRODERIE — Broderie"


def test_customization_option_can_have_compatible_materials() -> None:
    tenant = Tenant.objects.create(code="CAT-CUST2", name="Customization Tenant 2")
    with use_tenant(tenant.id):
        pes = CatalogMaterialReferenceFactory(tenant=tenant, code="PES", name="Polyester")
        option = CatalogCustomizationOptionFactory(
            tenant=tenant, technique=CatalogCustomizationOption.TECHNIQUE_SUBLIMATION
        )
        option.compatible_materials.set([pes])
        assert list(option.compatible_materials.values_list("code", flat=True)) == ["PES"]


# ---------------------------------------------------------------------------
# Commandes de chargement idempotentes
# ---------------------------------------------------------------------------


def test_load_epi_standards_creates_indicative_fixture_rows_and_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="CAT-EPICMD", name="EPI Command Tenant")
    call_command("load_epi_standards", tenant=tenant.code)
    call_command("load_epi_standards", tenant=tenant.code)
    with use_tenant(tenant.id):
        count = CatalogStandard.objects.filter(tenant=tenant).count()
        assert count == 25
        assert CatalogStandard.objects.filter(tenant=tenant, code="EN-ISO-20471").exists()


def test_load_customization_options_resolves_compatible_materials_by_code() -> None:
    tenant = Tenant.objects.create(code="CAT-CUSTCMD", name="Customization Command Tenant")
    call_command("load_material_references", tenant=tenant.code)
    call_command("load_customization_options", tenant=tenant.code)
    with use_tenant(tenant.id):
        assert CatalogCustomizationOption.objects.filter(tenant=tenant).count() == 7
        sublimation = CatalogCustomizationOption.objects.get(tenant=tenant, code="SUBLIMATION")
        assert list(sublimation.compatible_materials.values_list("code", flat=True)) == ["PES"]
        gravure = CatalogCustomizationOption.objects.get(tenant=tenant, code="GRAVURE")
        assert gravure.compatible_materials.count() == 0


def test_load_customization_options_is_idempotent() -> None:
    tenant = Tenant.objects.create(code="CAT-CUSTCMD2", name="Customization Command Tenant 2")
    call_command("load_material_references", tenant=tenant.code)
    call_command("load_customization_options", tenant=tenant.code)
    call_command("load_customization_options", tenant=tenant.code)
    with use_tenant(tenant.id):
        assert CatalogCustomizationOption.objects.filter(tenant=tenant).count() == 7


def test_load_customization_options_ignores_unknown_material_codes_silently() -> None:
    """Dependance d'ordre disclosed en docstring de la commande : si
    `load_material_references` n'a pas ete execute, les codes matiere du
    fixture sont simplement absents (aucune erreur), les options sont
    quand meme creees sans compatibilite renseignee."""
    tenant = Tenant.objects.create(code="CAT-CUSTCMD3", name="Customization Command Tenant 3")
    call_command("load_customization_options", tenant=tenant.code)
    with use_tenant(tenant.id):
        assert CatalogCustomizationOption.objects.filter(tenant=tenant).count() == 7
        sublimation = CatalogCustomizationOption.objects.get(tenant=tenant, code="SUBLIMATION")
        assert sublimation.compatible_materials.count() == 0


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def test_list_customization_options_endpoint_filters_by_compatible_material() -> None:
    tenant = Tenant.objects.create(code="CAT-CUSTAPI", name="Customization API Tenant")
    user = User.objects.create_user(email="cat-custapi@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "acheteur")
    with use_tenant(tenant.id):
        pes = CatalogMaterialReferenceFactory(tenant=tenant, code="PES", name="Polyester")
        coton = CatalogMaterialReferenceFactory(tenant=tenant, code="COTON", name="Coton")
        sublimation = CatalogCustomizationOptionFactory(
            tenant=tenant,
            code="SUBLIMATION",
            technique=CatalogCustomizationOption.TECHNIQUE_SUBLIMATION,
        )
        sublimation.compatible_materials.set([pes])
        CatalogCustomizationOptionFactory(
            tenant=tenant, code="GRAVURE", technique=CatalogCustomizationOption.TECHNIQUE_GRAVURE
        )

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": str(tenant.id)}

    response_all = client.get("/api/v1/catalog/customization-options", **headers)
    assert response_all.status_code == 200
    codes_all = {row["code"] for row in response_all.json()["results"]}
    assert codes_all == {"SUBLIMATION", "GRAVURE"}

    response_pes = client.get(
        f"/api/v1/catalog/customization-options?material_id={pes.id}", **headers
    )
    codes_pes = {row["code"] for row in response_pes.json()["results"]}
    assert codes_pes == {"SUBLIMATION"}

    response_coton = client.get(
        f"/api/v1/catalog/customization-options?material_id={coton.id}", **headers
    )
    assert response_coton.json()["results"] == []
