from __future__ import annotations

import datetime as dt

import pytest

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPeriod
from apps.accounting.services.chart_of_accounts import ensure_suspense_account, load_pcg2005
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="ACC-T", name="Accounting Tenant")


def test_fiscal_year_and_period_crud(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        period = AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fiscal_year,
            code="2026-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        assert period.fiscal_year_id == fiscal_year.id
        assert fiscal_year.state == AccFiscalYear.STATE_OPEN
        assert period.state == AccPeriod.STATE_OPEN


def test_account_tree_via_parent(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        root = AccAccount.objects.create(
            tenant=tenant,
            code="40",
            name="Fournisseurs et comptes rattaches",
            account_class=4,
            type=AccAccount.TYPE_PAYABLE,
        )
        child = AccAccount.objects.create(
            tenant=tenant,
            code="401",
            name="Fournisseurs",
            account_class=4,
            type=AccAccount.TYPE_PAYABLE,
            parent=root,
        )
        assert child.parent_id == root.id
        assert root.children.count() == 1


def test_journal_creation(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        account = AccAccount.objects.create(
            tenant=tenant,
            code="411",
            name="Clients",
            account_class=4,
            type=AccAccount.TYPE_RECEIVABLE,
        )
        journal = AccJournal.objects.create(
            tenant=tenant,
            code="VTE",
            name="Journal des ventes",
            type=AccJournal.TYPE_SALE,
            default_account=account,
            sequence_prefix="VTE",
        )
        assert journal.default_account_id == account.id


def test_load_pcg2005_creates_accounts_from_fixture(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        created = load_pcg2005(tenant)
        assert created > 0
        assert AccAccount.objects.filter(tenant=tenant, code="411").exists()
        assert AccAccount.objects.filter(tenant=tenant, code="4457").exists()


def test_load_pcg2005_is_idempotent(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        first_run = load_pcg2005(tenant)
        second_run = load_pcg2005(tenant)
        assert first_run > 0
        assert second_run == 0


def test_ensure_suspense_account_creates_a_placeholder_account(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        account = ensure_suspense_account(tenant)
        assert account.is_placeholder is True
        assert account.code == "471"


def test_ensure_suspense_account_is_idempotent(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        first = ensure_suspense_account(tenant)
        second = ensure_suspense_account(tenant)
        count = AccAccount.objects.filter(tenant=tenant, is_placeholder=True).count()
        assert first.id == second.id
        assert count == 1
