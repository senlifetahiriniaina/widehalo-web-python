from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from apps.accounting.models import (
    AccAccount,
    AccFiscalYear,
    AccJournal,
    AccPaymentTerm,
    AccPeriod,
    AccTax,
)
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def config_screens_setup():
    tenant = Tenant.objects.create(code="UI-ACC-CFG", name="UI Accounting Config Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="ui-acc-cfg@example.com", password="Str0ngPassw0rd!23"
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant


def test_config_index_renders(config_screens_setup) -> None:
    client, _tenant = config_screens_setup
    response = client.get("/accounting/config/")
    assert response.status_code == 200


def test_config_fiscal_years_get(config_screens_setup) -> None:
    client, _tenant = config_screens_setup
    response = client.get("/accounting/config/fiscal-years/")
    assert response.status_code == 200


def test_config_fiscal_years_create(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    response = client.post(
        "/accounting/config/fiscal-years/",
        {"code": "2026", "date_start": "2026-01-01", "date_end": "2026-12-31"},
    )
    assert response.status_code == 200
    assert b"2026" in response.content
    with use_tenant(tenant.id):
        assert AccFiscalYear.objects.filter(code="2026").exists()


def test_config_periods_create(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    with use_tenant(tenant.id):
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
    response = client.post(
        "/accounting/config/periods/",
        {
            "fiscal_year_id": str(fiscal_year.id),
            "code": "2026-01",
            "date_start": "2026-01-01",
            "date_end": "2026-01-31",
        },
    )
    assert response.status_code == 200
    assert b"2026-01" in response.content
    with use_tenant(tenant.id):
        assert AccPeriod.objects.filter(code="2026-01").exists()


def test_config_journals_create(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    response = client.post(
        "/accounting/config/journals/",
        {
            "code": "VTE",
            "name": "Ventes",
            "type": AccJournal.TYPE_SALE,
            "sequence_prefix": "VTE",
            "currency": "MGA",
        },
    )
    assert response.status_code == 200
    assert b"Ventes" in response.content
    with use_tenant(tenant.id):
        assert AccJournal.objects.filter(code="VTE").exists()


def test_config_accounts_create(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    response = client.post(
        "/accounting/config/accounts/",
        {
            "code": "411000",
            "name": "Clients",
            "account_class": "4",
            "type": AccAccount.TYPE_RECEIVABLE,
            "currency": "MGA",
        },
    )
    assert response.status_code == 200
    assert b"411000" in response.content
    with use_tenant(tenant.id):
        assert AccAccount.objects.filter(code="411000").exists()


def test_config_taxes_create(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    with use_tenant(tenant.id):
        account_collected = AccAccount.objects.create(
            tenant=tenant, code="4457", name="TVA collectee", account_class=4, type="tax"
        )
    response = client.post(
        "/accounting/config/taxes/",
        {
            "code": "TVA20",
            "name": "TVA 20%",
            "type": AccTax.TYPE_SALE,
            "rate": "20",
            "account_collected_id": str(account_collected.id),
        },
    )
    assert response.status_code == 200
    assert b"TVA20" in response.content
    with use_tenant(tenant.id):
        assert AccTax.objects.filter(code="TVA20").exists()


def test_config_payment_terms_create(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    response = client.post(
        "/accounting/config/payment-terms/",
        {"name": "30 jours net", "value_type": "balance", "days": "30"},
    )
    assert response.status_code == 200
    assert b"30 jours net" in response.content
    with use_tenant(tenant.id):
        term = AccPaymentTerm.objects.get(name="30 jours net")
        assert term.lines.count() == 1
        line = term.lines.first()
        assert line.days == 30
        assert line.value is None


def test_config_payment_terms_create_percent_persists_value(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    response = client.post(
        "/accounting/config/payment-terms/",
        {"name": "30% a 30 jours", "value_type": "percent", "value": "30", "days": "30"},
    )
    assert response.status_code == 200
    with use_tenant(tenant.id):
        term = AccPaymentTerm.objects.get(name="30% a 30 jours")
        line = term.lines.first()
        assert line.value_type == "percent"
        assert line.value == Decimal("30")


def test_config_payment_terms_create_fixed_persists_value(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    response = client.post(
        "/accounting/config/payment-terms/",
        {"name": "Acompte fixe", "value_type": "fixed", "value": "50000", "days": "0"},
    )
    assert response.status_code == 200
    with use_tenant(tenant.id):
        term = AccPaymentTerm.objects.get(name="Acompte fixe")
        line = term.lines.first()
        assert line.value_type == "fixed"
        assert line.value == Decimal("50000")


def test_config_payment_terms_percent_without_value_shows_error(config_screens_setup) -> None:
    client, tenant = config_screens_setup
    response = client.post(
        "/accounting/config/payment-terms/",
        {"name": "Sans valeur", "value_type": "percent", "days": "30"},
    )
    assert response.status_code == 200
    assert b"requise" in response.content
    with use_tenant(tenant.id):
        assert not AccPaymentTerm.objects.filter(name="Sans valeur").exists()
