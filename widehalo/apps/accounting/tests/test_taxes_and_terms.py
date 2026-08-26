from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccExchangeRate, AccPaymentTerm, AccPaymentTermLine, AccTax
from apps.accounting.services.currency import convert_to_mga
from apps.accounting.services.payment_terms import generate_due_lines
from apps.accounting.services.taxes import applicable_taxes, vat_applicable
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def test_vat_is_not_applicable_for_synthetic_regime() -> None:
    tenant = Tenant.objects.create(
        code="ACC-SYN", name="Synthetique SARL", fiscal_regime=Tenant.FISCAL_REGIME_SYNTHETIC
    )
    with use_tenant(tenant.id):
        AccTax.objects.create(
            tenant=tenant, code="TVA20", name="TVA 20%", type=AccTax.TYPE_SALE, rate=Decimal(20)
        )
        assert not vat_applicable(tenant)
        assert applicable_taxes(tenant) == []


def test_vat_is_applicable_for_real_regime_with_vat() -> None:
    tenant = Tenant.objects.create(
        code="ACC-REEL", name="Reel SARL", fiscal_regime=Tenant.FISCAL_REGIME_REAL_WITH_VAT
    )
    with use_tenant(tenant.id):
        tax = AccTax.objects.create(
            tenant=tenant, code="TVA20", name="TVA 20%", type=AccTax.TYPE_SALE, rate=Decimal(20)
        )
        assert vat_applicable(tenant)
        assert applicable_taxes(tenant) == [tax]


def test_payment_term_30_40_30_generates_three_lines_at_correct_dates() -> None:
    tenant = Tenant.objects.create(code="ACC-TERM", name="Terms SARL")
    with use_tenant(tenant.id):
        term = AccPaymentTerm.objects.create(tenant=tenant, name="30/40/30")
        AccPaymentTermLine.objects.create(
            tenant=tenant,
            term=term,
            sequence=1,
            value_type=AccPaymentTermLine.VALUE_TYPE_PERCENT,
            value=Decimal(30),
            days=0,
        )
        AccPaymentTermLine.objects.create(
            tenant=tenant,
            term=term,
            sequence=2,
            value_type=AccPaymentTermLine.VALUE_TYPE_PERCENT,
            value=Decimal(40),
            days=30,
        )
        AccPaymentTermLine.objects.create(
            tenant=tenant,
            term=term,
            sequence=3,
            value_type=AccPaymentTermLine.VALUE_TYPE_PERCENT,
            value=Decimal(30),
            days=60,
        )

        due_lines = generate_due_lines(term, Decimal(1000), dt.date(2026, 1, 1))

        assert len(due_lines) == 3
        assert due_lines[0] == (Decimal("300.0000"), dt.date(2026, 1, 1))
        assert due_lines[1] == (Decimal("400.0000"), dt.date(2026, 1, 31))
        assert due_lines[2] == (Decimal("300.0000"), dt.date(2026, 3, 2))
        assert sum(amount for amount, _ in due_lines) == Decimal("1000.0000")


def test_payment_term_balance_line_absorbs_rounding() -> None:
    tenant = Tenant.objects.create(code="ACC-TERM2", name="Terms SARL 2")
    with use_tenant(tenant.id):
        term = AccPaymentTerm.objects.create(tenant=tenant, name="Comptant + solde")
        AccPaymentTermLine.objects.create(
            tenant=tenant,
            term=term,
            sequence=1,
            value_type=AccPaymentTermLine.VALUE_TYPE_FIXED,
            value=Decimal("333.33"),
        )
        AccPaymentTermLine.objects.create(
            tenant=tenant,
            term=term,
            sequence=2,
            value_type=AccPaymentTermLine.VALUE_TYPE_BALANCE,
            days=30,
        )

        due_lines = generate_due_lines(term, Decimal(1000), dt.date(2026, 1, 1))
        assert sum(amount for amount, _ in due_lines) == Decimal(1000)


def test_convert_to_mga_uses_the_rate_of_the_day() -> None:
    tenant = Tenant.objects.create(code="ACC-FX", name="FX SARL")
    with use_tenant(tenant.id):
        AccExchangeRate.objects.create(
            tenant=tenant, currency="EUR", date=dt.date(2026, 1, 10), rate_to_mga=Decimal("4800")
        )
        AccExchangeRate.objects.create(
            tenant=tenant, currency="EUR", date=dt.date(2026, 1, 20), rate_to_mga=Decimal("4850")
        )

        converted = convert_to_mga(Decimal(100), "EUR", dt.date(2026, 1, 15), tenant=tenant)
        assert converted == Decimal("480000.0000")  # taux du 10/01, le plus recent <= 15/01


def test_convert_to_mga_without_a_known_rate_raises() -> None:
    tenant = Tenant.objects.create(code="ACC-FX2", name="FX SARL 2")
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        convert_to_mga(Decimal(100), "EUR", dt.date(2026, 1, 15), tenant=tenant)


def test_base_currency_conversion_is_a_no_op() -> None:
    tenant = Tenant.objects.create(code="ACC-FX3", name="FX SARL 3")
    with use_tenant(tenant.id):
        assert convert_to_mga(Decimal(100), "MGA", dt.date(2026, 1, 15), tenant=tenant) == Decimal(
            100
        )
