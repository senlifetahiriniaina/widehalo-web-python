from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccExchangeRate, AccPaymentTerm, AccPaymentTermLine, AccTax
from apps.accounting.services.currency import convert_to_mga
from apps.accounting.services.payment_terms import generate_due_lines
from apps.accounting.services.public import get_default_sale_tax
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


def test_vat_is_not_applicable_for_the_real_regime_without_vat() -> None:
    """L5 — le regime que `vat_applicable` classait du mauvais cote.

    `reel_sans_tva` porte le libelle « Réel, sans assujettissement TVA » :
    des trois regimes, c'est le seul dont le NOM dit la non-assujettissement,
    et c'etait le seul que la fonction declarait assujetti (elle ne comparait
    qu'au regime synthetique). Sans ce test, les trois regimes restaient
    couverts a deux."""
    tenant = Tenant.objects.create(
        code="ACC-REEL-SANS",
        name="Reel sans TVA SARL",
        fiscal_regime=Tenant.FISCAL_REGIME_REAL_NO_VAT,
    )
    with use_tenant(tenant.id):
        AccTax.objects.create(
            tenant=tenant, code="TVA20", name="TVA 20%", type=AccTax.TYPE_SALE, rate=Decimal(20)
        )
        assert not vat_applicable(tenant)
        assert applicable_taxes(tenant) == []


def test_the_2026_vat_option_makes_a_real_regime_without_vat_liable() -> None:
    """`Tenant.vat_opted_in` (ACC-SMT1, Loi de Finances 2026) : premier
    lecteur du champ dans tout le depot. Meme tenant, meme taxe que le test
    precedent — seule l'option change."""
    tenant = Tenant.objects.create(
        code="ACC-OPTION",
        name="Optant SARL",
        fiscal_regime=Tenant.FISCAL_REGIME_REAL_NO_VAT,
        vat_opted_in=True,
    )
    with use_tenant(tenant.id):
        tax = AccTax.objects.create(
            tenant=tenant, code="TVA20", name="TVA 20%", type=AccTax.TYPE_SALE, rate=Decimal(20)
        )
        assert vat_applicable(tenant)
        assert applicable_taxes(tenant) == [tax]


def test_the_option_never_reopens_vat_for_a_synthetic_regime() -> None:
    """L'option vise la tranche de chiffre d'affaires REEL, pas le forfait :
    un `vat_opted_in` coche par erreur sur un tenant synthetique reste sans
    effet (RG-ACC-5). Sans cette assertion, « lire le champ » et « lire le
    champ n'importe ou » seraient indiscernables."""
    tenant = Tenant.objects.create(
        code="ACC-SYN-OPT",
        name="Synthetique optant SARL",
        fiscal_regime=Tenant.FISCAL_REGIME_SYNTHETIC,
        vat_opted_in=True,
    )
    with use_tenant(tenant.id):
        assert not vat_applicable(tenant)


def test_the_default_sale_tax_is_never_proposed_to_a_non_liable_tenant() -> None:
    """RG-ACC-5 exige que la taxe ne soit ni APPLIQUEE ni PROPOSEE. Les deux
    surfaces qui repondent a cette question se contredisaient :
    `applicable_taxes` masquait bien la taxe, mais
    `public.get_default_sale_tax` — celle qu'appellent reellement le POS et,
    depuis L5, `sales` — interrogeait `AccTax` sans jamais lire le regime.
    C'est la surface consommee qui avait tort."""
    tenant = Tenant.objects.create(
        code="ACC-PROPOSE",
        name="Non assujetti SARL",
        fiscal_regime=Tenant.FISCAL_REGIME_REAL_NO_VAT,
    )
    with use_tenant(tenant.id):
        AccTax.objects.create(
            tenant=tenant, code="TVA20", name="TVA 20%", type=AccTax.TYPE_SALE, rate=Decimal(20)
        )
        assert get_default_sale_tax(tenant) is None

        tenant.vat_opted_in = True
        tenant.save(update_fields=["vat_opted_in"])
        proposed = get_default_sale_tax(tenant)
        assert proposed is not None and proposed["rate"] == Decimal(20)
