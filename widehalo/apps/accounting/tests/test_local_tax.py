"""A11 — ACC-FONCIER (`services/local_tax.py`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.accounting.models import AccFiscalYear, AccLocalTax
from apps.accounting.services.local_tax import record_local_tax
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def local_tax_fiscal_year():
    tenant = Tenant.objects.create(code="ACC-FONCIER", name="Foncier Tenant")
    with use_tenant(tenant.id):
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        return {"tenant": tenant, "fiscal_year": fiscal_year}


def test_record_local_tax_ift_computes_amount_due(local_tax_fiscal_year) -> None:
    tenant = local_tax_fiscal_year["tenant"]
    fiscal_year = local_tax_fiscal_year["fiscal_year"]
    with use_tenant(tenant.id):
        local_tax = record_local_tax(
            tenant=tenant,
            tax_type=AccLocalTax.TAX_TYPE_IFT,
            property_label="Terrain nu Ankorondrano",
            assessed_value_mga=Decimal("50000000"),
            rate_pct=Decimal("1"),
            fiscal_year=fiscal_year,
        )
        assert local_tax.reference
        assert local_tax.amount_due_mga == Decimal("500000.0000")
        assert local_tax.state == AccLocalTax.STATE_DRAFT


def test_record_local_tax_ifpb_uses_explicit_rate(local_tax_fiscal_year) -> None:
    tenant = local_tax_fiscal_year["tenant"]
    fiscal_year = local_tax_fiscal_year["fiscal_year"]
    with use_tenant(tenant.id):
        local_tax = record_local_tax(
            tenant=tenant,
            tax_type=AccLocalTax.TAX_TYPE_IFPB,
            property_label="Atelier Andraharo",
            assessed_value_mga=Decimal("20000000"),
            rate_pct=Decimal("7.5"),
            fiscal_year=fiscal_year,
        )
        assert local_tax.amount_due_mga == Decimal("1500000.0000")
