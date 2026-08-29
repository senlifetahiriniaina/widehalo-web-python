"""REF1 (enrichissement referentiel LIFE MDG, cf. plan) : format de code
Pantone sur `AttributeValue` et referentiel `CatalogMaterialReference`.

**Reserve legale explicite** : aucune valeur colorimetrique RGB/hex
proprietaire Pantone n'est chargee ici — uniquement le format du code
(`NN-NNNN TCX`)."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.test import Client

from apps.catalog.models import CatalogMaterialReference
from apps.catalog.services.material_reference import (
    set_attribute_value_color_reference,
    validate_hex_approximation,
    validate_pantone_code,
)
from apps.catalog.tests.factories import AttributeValueFactory, CatalogMaterialReferenceFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Format de code Pantone (regex, aucune valeur proprietaire)
# ---------------------------------------------------------------------------


def test_validate_pantone_code_accepts_the_nn_nnnn_tcx_format() -> None:
    validate_pantone_code("")
    validate_pantone_code("19-4052 TCX")


@pytest.mark.parametrize(
    "value",
    ["19-4052", "194052 TCX", "1-4052 TCX", "19-405 TCX", "19-4052TCX", "abcde"],
)
def test_validate_pantone_code_rejects_anything_else(value: str) -> None:
    with pytest.raises(ValidationError):
        validate_pantone_code(value)


def test_validate_hex_approximation_accepts_rrggbb_format() -> None:
    validate_hex_approximation("")
    validate_hex_approximation("#1A2B3C")


@pytest.mark.parametrize("value", ["1A2B3C", "#1A2B3", "#GGGGGG"])
def test_validate_hex_approximation_rejects_anything_else(value: str) -> None:
    with pytest.raises(ValidationError):
        validate_hex_approximation(value)


def test_set_attribute_value_color_reference_persists_valid_format() -> None:
    tenant = Tenant.objects.create(code="CAT-PANT1", name="Pantone Tenant 1")
    with use_tenant(tenant.id):
        value = AttributeValueFactory(tenant=tenant)
        updated = set_attribute_value_color_reference(
            value, pantone_code="19-4052 TCX", hex_approximation="#1A2B3C"
        )
        updated.refresh_from_db()
        assert updated.pantone_code == "19-4052 TCX"
        assert updated.hex_approximation == "#1A2B3C"


def test_set_attribute_value_color_reference_rejects_invalid_pantone_code() -> None:
    tenant = Tenant.objects.create(code="CAT-PANT2", name="Pantone Tenant 2")
    with use_tenant(tenant.id):
        value = AttributeValueFactory(tenant=tenant)
        with pytest.raises(ValidationError):
            set_attribute_value_color_reference(value, pantone_code="not-a-code")
        value.refresh_from_db()
        assert value.pantone_code == ""


# ---------------------------------------------------------------------------
# `CatalogMaterialReference`
# ---------------------------------------------------------------------------


def test_material_reference_str_shows_code_and_name() -> None:
    tenant = Tenant.objects.create(code="CAT-MAT1", name="Material Tenant 1")
    with use_tenant(tenant.id):
        material = CatalogMaterialReferenceFactory(tenant=tenant, code="NOMEX", name="Nomex")
        assert str(material) == "NOMEX — Nomex"


def test_material_reference_gsm_fields_are_decimal_and_optional() -> None:
    tenant = Tenant.objects.create(code="CAT-MAT2", name="Material Tenant 2")
    with use_tenant(tenant.id):
        nature = CatalogMaterialReference.NATURE_NATURELLE_PROTEIQUE
        material = CatalogMaterialReference.objects.create(
            tenant=tenant, code="SOIE", name="Soie", nature=nature
        )
        assert material.typical_gsm_min is None
        assert material.typical_gsm_max is None


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


def test_list_material_references_endpoint_returns_active_entries() -> None:
    tenant = Tenant.objects.create(code="CAT-MATAPI1", name="Material API Tenant 1")
    user = User.objects.create_user(email="cat-matapi1@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "acheteur")
    with use_tenant(tenant.id):
        CatalogMaterialReferenceFactory(tenant=tenant, code="COTON", name="Coton")

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": str(tenant.id)}

    response = client.get("/api/v1/catalog/material-references", **headers)
    assert response.status_code == 200
    codes = {row["code"] for row in response.json()["results"]}
    assert codes == {"COTON"}


def test_set_color_reference_endpoint_validates_pantone_format() -> None:
    tenant = Tenant.objects.create(code="CAT-MATAPI2", name="Material API Tenant 2")
    user = User.objects.create_user(email="cat-matapi2@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "acheteur")
    with use_tenant(tenant.id):
        value = AttributeValueFactory(tenant=tenant)

    client = Client()
    token = _access_token(client, user.email, "Str0ngPassw0rd!23")
    headers = {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": str(tenant.id)}

    bad_response = client.post(
        f"/api/v1/catalog/attribute-values/{value.id}/color-reference",
        {"pantone_code": "invalid"},
        content_type="application/json",
        **headers,
    )
    assert bad_response.status_code == 400

    ok_response = client.post(
        f"/api/v1/catalog/attribute-values/{value.id}/color-reference",
        {"pantone_code": "19-4052 TCX", "hex_approximation": "#1A2B3C"},
        content_type="application/json",
        **headers,
    )
    assert ok_response.status_code == 200
    assert ok_response.json()["pantone_code"] == "19-4052 TCX"
