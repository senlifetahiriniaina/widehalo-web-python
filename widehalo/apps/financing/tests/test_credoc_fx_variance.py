from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccExchangeRate
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.financing.services.credoc import create_credoc, credoc_fx_variance

pytestmark = pytest.mark.django_db


def test_create_credoc_rejects_foreign_currency_without_amount_foreign() -> None:
    tenant = Tenant.objects.create(code="FIN-FX1", name="Financing FX Tenant 1")
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_credoc(
            tenant,
            purchase_order_id=uuid.uuid4(),
            bank="Banque emettrice",
            beneficiary="Fournisseur import",
            amount_mga=Decimal("30000000"),
            validity_date=dt.date(2026, 12, 31),
            currency="EUR",
        )


def test_credoc_fx_variance_is_none_for_mga_credoc() -> None:
    tenant = Tenant.objects.create(code="FIN-FX2", name="Financing FX Tenant 2")
    with use_tenant(tenant.id):
        credoc = create_credoc(
            tenant,
            purchase_order_id=uuid.uuid4(),
            bank="Banque emettrice",
            beneficiary="Fournisseur import",
            amount_mga=Decimal("30000000"),
            validity_date=dt.date(2026, 12, 31),
        )
        assert credoc_fx_variance(credoc) is None


def test_credoc_fx_variance_is_none_without_amount_foreign_even_if_currency_set() -> None:
    tenant = Tenant.objects.create(code="FIN-FX3", name="Financing FX Tenant 3")
    with use_tenant(tenant.id):
        credoc = create_credoc(
            tenant,
            purchase_order_id=uuid.uuid4(),
            bank="Banque emettrice",
            beneficiary="Fournisseur import",
            amount_mga=Decimal("30000000"),
            validity_date=dt.date(2026, 12, 31),
            currency="EUR",
            amount_foreign=Decimal("6000"),
        )
        credoc.amount_foreign = None
        credoc.save(update_fields=["amount_foreign"])
        assert credoc_fx_variance(credoc) is None


def test_credoc_fx_variance_flags_material_gap() -> None:
    tenant = Tenant.objects.create(code="FIN-FX4", name="Financing FX Tenant 4")
    with use_tenant(tenant.id):
        AccExchangeRate.objects.create(
            tenant=tenant, currency="EUR", date=dt.date(2026, 1, 1), rate_to_mga=Decimal("5000")
        )
        credoc = create_credoc(
            tenant,
            purchase_order_id=uuid.uuid4(),
            bank="Banque emettrice",
            beneficiary="Fournisseur import",
            amount_mga=Decimal("30000000"),
            validity_date=dt.date(2026, 12, 31),
            currency="EUR",
            amount_foreign=Decimal("6000"),
        )
        AccExchangeRate.objects.create(
            tenant=tenant, currency="EUR", date=dt.date(2026, 2, 1), rate_to_mga=Decimal("5400")
        )
        result = credoc_fx_variance(credoc, as_of=dt.date(2026, 2, 1))
        assert result is not None
        assert result["booked_amount_mga"] == Decimal("30000000")
        assert result["current_amount_mga"] == Decimal("32400000.0000")
        assert result["variance_mga"] == Decimal("2400000.0000")
        assert result["variance_pct"].quantize(Decimal("0.01")) == Decimal("8.00")
        assert result["is_material"] is True


def test_credoc_fx_variance_not_material_under_threshold() -> None:
    tenant = Tenant.objects.create(code="FIN-FX5", name="Financing FX Tenant 5")
    with use_tenant(tenant.id):
        AccExchangeRate.objects.create(
            tenant=tenant, currency="EUR", date=dt.date(2026, 1, 1), rate_to_mga=Decimal("5000")
        )
        credoc = create_credoc(
            tenant,
            purchase_order_id=uuid.uuid4(),
            bank="Banque emettrice",
            beneficiary="Fournisseur import",
            amount_mga=Decimal("30000000"),
            validity_date=dt.date(2026, 12, 31),
            currency="EUR",
            amount_foreign=Decimal("6000"),
        )
        AccExchangeRate.objects.create(
            tenant=tenant, currency="EUR", date=dt.date(2026, 2, 1), rate_to_mga=Decimal("5005")
        )
        result = credoc_fx_variance(credoc, as_of=dt.date(2026, 2, 1))
        assert result is not None
        assert result["is_material"] is False
