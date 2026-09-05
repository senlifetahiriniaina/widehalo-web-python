"""Bloc F, F1 : `GET /api/v1/forecast/material-needs` — seul point
d'entrée réel de `services.material_needs.compute_material_needs`.
Mintage JWT direct (même patron que `apps.core.tests.test_rbac_matrix`/
`apps.payroll.tests.test_rbac_full_matrix`) : l'API n'est jamais gatée
par la MFA (seul l'accès web par session l'est, cf. `apps.core.
middleware.MFAEnforcementMiddleware`)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from apps.catalog.models import ProductTemplate, ProductVariant, UnitOfMeasure
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.sales.tests.factories import SalesForecastFactory
from apps.stocks.tests.factories import StkQuantFactory
from django.test import Client
from ninja_jwt.tokens import RefreshToken

pytestmark = pytest.mark.django_db


def _headers(token: str, tenant_id: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


@pytest.fixture
def material_needs_setup():
    tenant = Tenant.objects.create(code="FOR-F1-API", name="Forecast F1 API Tenant")
    with use_tenant(tenant.id):
        uom = UnitOfMeasure.objects.create(
            tenant=tenant, code="PC-F1API", name="Piece", category=UnitOfMeasure.CATEGORY_COUNT
        )
        finished_template = ProductTemplate.objects.create(
            tenant=tenant, name="Produit fini API", base_uom=uom
        )
        finished_variant = ProductVariant.objects.create(tenant=tenant, template=finished_template)
        SalesForecastFactory(
            tenant=tenant, variant_id=finished_variant.id, period="2026-01", qty_forecast=6
        )
        component_template = ProductTemplate.objects.create(
            tenant=tenant, name="Composant API", base_uom=uom
        )
        component_variant = ProductVariant.objects.create(
            tenant=tenant, template=component_template
        )
        bom = create_bom(tenant=tenant, code="BOM-F1-API", product_template_id=finished_template.id)
        add_bom_line(
            bom,
            component_template_id=component_template.id,
            component_variant_id=component_variant.id,
            qty=Decimal("2"),
        )
        activate_bom(bom)
        StkQuantFactory(tenant=tenant, variant_id=component_variant.id, qty=Decimal(5))

        user = User.objects.create_user(email="direction-f1@example.com", password="x")
        grant_role(user, "direction")
    return tenant, component_variant.id


def test_material_needs_endpoint_requires_permission(material_needs_setup) -> None:
    tenant, _component_variant_id = material_needs_setup
    unauthorized = User.objects.create_user(email="commercial-f1@example.com", password="x")
    token = str(RefreshToken.for_user(unauthorized).access_token)

    response = Client().get(
        "/api/v1/forecast/material-needs",
        {"period_from": "2026-01", "period_to": "2026-01"},
        **_headers(token, str(tenant.id)),
    )

    assert response.status_code == 403


def test_material_needs_endpoint_returns_computed_needs(material_needs_setup) -> None:
    tenant, component_variant_id = material_needs_setup
    with use_tenant(tenant.id):
        user = User.objects.get(email="direction-f1@example.com")
    token = str(RefreshToken.for_user(user).access_token)

    response = Client().get(
        "/api/v1/forecast/material-needs",
        {"period_from": "2026-01", "period_to": "2026-01"},
        **_headers(token, str(tenant.id)),
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    need = body["results"][0]
    assert need["component_variant_id"] == str(component_variant_id)
    assert Decimal(need["gross_need"]) == Decimal(12)  # 6 * 2
    assert Decimal(need["net_need"]) == Decimal(7)  # 12 - 5
