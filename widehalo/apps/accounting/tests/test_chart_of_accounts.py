from __future__ import annotations

import datetime as dt

import pytest

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPeriod
from apps.accounting.services.chart_of_accounts import (
    ensure_default_journals,
    ensure_suspense_account,
    load_pcg2005,
)
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
        assert created == 54
        assert AccAccount.objects.filter(tenant=tenant, code="411").exists()
        assert AccAccount.objects.filter(tenant=tenant, code="4457").exists()


def test_load_pcg2005_is_idempotent(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        first_run = load_pcg2005(tenant)
        second_run = load_pcg2005(tenant)
        assert first_run == 54
        assert second_run == 0


def test_load_pcg2005_tags_sector_specific_accounts(tenant: Tenant) -> None:
    """Les comptes sectoriels (UXR7) portent leur `sector_code`, les 39
    comptes generiques historiques restent `sector_code=None`."""
    with use_tenant(tenant.id):
        load_pcg2005(tenant)
        textile_account = AccAccount.objects.get(tenant=tenant, code="3111")
        assert textile_account.sector_code == AccAccount.SECTOR_TEXTILE
        leather_account = AccAccount.objects.get(tenant=tenant, code="6012")
        assert leather_account.sector_code == AccAccount.SECTOR_LEATHER
        generic_account = AccAccount.objects.get(tenant=tenant, code="411")
        assert generic_account.sector_code is None
        assert AccAccount.objects.filter(tenant=tenant, sector_code__isnull=False).count() == 15


def test_ensure_default_journals_creates_seven_journals(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        load_pcg2005(tenant)
        created = ensure_default_journals(tenant)
        assert created == 7
        assert AccJournal.objects.filter(tenant=tenant).count() == 7
        codes = set(AccJournal.objects.filter(tenant=tenant).values_list("code", flat=True))
        assert codes == {"VTE", "ACH", "BQ", "CAI", "OD", "PAI", "STK"}

        bank = AccJournal.objects.get(tenant=tenant, code="BQ")
        assert bank.type == AccJournal.TYPE_BANK
        assert bank.default_account is not None
        assert bank.default_account.code == "512"

        cash = AccJournal.objects.get(tenant=tenant, code="CAI")
        assert cash.type == AccJournal.TYPE_CASH
        assert cash.default_account is not None
        assert cash.default_account.code == "530"

        sale = AccJournal.objects.get(tenant=tenant, code="VTE")
        assert sale.type == AccJournal.TYPE_SALE
        assert sale.default_account is None


def test_ensure_default_journals_without_matching_accounts_leaves_default_account_none(
    tenant: Tenant,
) -> None:
    """Aucune exception si le plan comptable n'a pas (encore) ete charge —
    `default_account` reste simplement `None`."""
    with use_tenant(tenant.id):
        created = ensure_default_journals(tenant)
        assert created == 7
        bank = AccJournal.objects.get(tenant=tenant, code="BQ")
        assert bank.default_account is None
        cash = AccJournal.objects.get(tenant=tenant, code="CAI")
        assert cash.default_account is None


def test_ensure_default_journals_is_idempotent(tenant: Tenant) -> None:
    with use_tenant(tenant.id):
        load_pcg2005(tenant)
        first_run = ensure_default_journals(tenant)
        second_run = ensure_default_journals(tenant)
        assert first_run == 7
        assert second_run == 0
        assert AccJournal.objects.filter(tenant=tenant).count() == 7


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
