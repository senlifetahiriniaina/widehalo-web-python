"""A10 — immobilisations/amortissements/provisions (`services/assets.py`)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccAccount, AccAsset, AccFiscalYear, AccJournal, AccPeriod
from apps.accounting.services.assets import (
    compute_annual_depreciation,
    dispose_asset,
    record_provision_movement,
    register_asset,
)
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _make_account(tenant, *, code, name, account_class, type):
    return AccAccount.objects.create(
        tenant=tenant, code=code, name=name, account_class=account_class, type=type
    )


@pytest.fixture
def asset_ledger():
    tenant = Tenant.objects.create(code="ACC-A10", name="Accounting A10 Tenant")
    with use_tenant(tenant.id):
        fy2026 = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        fy2027 = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2027",
            date_start=dt.date(2027, 1, 1),
            date_end=dt.date(2027, 12, 31),
        )
        period2026 = AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fy2026,
            code="2026-12",
            date_start=dt.date(2026, 12, 1),
            date_end=dt.date(2026, 12, 31),
        )
        journal = AccJournal.objects.create(
            tenant=tenant,
            code="OD",
            name="Operations diverses",
            type=AccJournal.TYPE_MISC,
            sequence_prefix="OD",
        )
        immo_account = _make_account(
            tenant,
            code="2183",
            name="Materiel de bureau",
            account_class=2,
            type=AccAccount.TYPE_ASSET,
        )
        return tenant, fy2026, fy2027, period2026, journal, immo_account


def test_register_asset_rejects_degressif(asset_ledger) -> None:
    tenant, fy2026, fy2027, period2026, journal, immo_account = asset_ledger
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        register_asset(
            tenant=tenant,
            category=AccAsset.CATEGORY_CORPORELLE,
            label="Machine X",
            account=immo_account,
            acquisition_date=dt.date(2026, 1, 1),
            acquisition_value_mga=Decimal("1000000"),
            depreciation_method=AccAsset.METHOD_DEGRESSIF,
            useful_life_years=5,
        )


def test_register_asset_creates_acquisition_movement(asset_ledger) -> None:
    tenant, fy2026, fy2027, period2026, journal, immo_account = asset_ledger
    with use_tenant(tenant.id):
        asset = register_asset(
            tenant=tenant,
            category=AccAsset.CATEGORY_CORPORELLE,
            label="Machine X",
            account=immo_account,
            acquisition_date=dt.date(2026, 1, 1),
            acquisition_value_mga=Decimal("1000000"),
            depreciation_method=AccAsset.METHOD_LINEAIRE,
            useful_life_years=5,
        )
        assert asset.state == AccAsset.STATE_ACTIVE
        assert asset.reference
        movements = list(asset.movements.all())
        assert len(movements) == 1
        assert movements[0].movement_type == "acquisition"
        assert movements[0].move is None


def test_compute_annual_depreciation_full_year(asset_ledger) -> None:
    tenant, fy2026, fy2027, period2026, journal, immo_account = asset_ledger
    with use_tenant(tenant.id):
        asset = register_asset(
            tenant=tenant,
            category=AccAsset.CATEGORY_CORPORELLE,
            label="Machine X",
            account=immo_account,
            acquisition_date=dt.date(2026, 1, 1),
            acquisition_value_mga=Decimal("1000000"),
            depreciation_method=AccAsset.METHOD_LINEAIRE,
            useful_life_years=5,
        )
        entry = compute_annual_depreciation(asset, fy2026)
        assert entry.opening_accumulated_mga == Decimal("0.0000")
        assert entry.annual_dotation_mga == Decimal("200000.0000")
        assert entry.closing_accumulated_mga == Decimal("200000.0000")
        assert entry.move is None


def test_compute_annual_depreciation_prorated_first_year(asset_ledger) -> None:
    tenant, fy2026, fy2027, period2026, journal, immo_account = asset_ledger
    with use_tenant(tenant.id):
        # Acquis le 1er juillet 2026 : ~184 jours detenus sur 365 (annee non
        # bissextile) -> dotation ~= annuite pleine * 184/365.
        asset = register_asset(
            tenant=tenant,
            category=AccAsset.CATEGORY_CORPORELLE,
            label="Machine Y",
            account=immo_account,
            acquisition_date=dt.date(2026, 7, 1),
            acquisition_value_mga=Decimal("1000000"),
            depreciation_method=AccAsset.METHOD_LINEAIRE,
            useful_life_years=5,
        )
        entry = compute_annual_depreciation(asset, fy2026)
        days_held = (dt.date(2026, 12, 31) - dt.date(2026, 7, 1)).days + 1
        expected = (Decimal("200000") * Decimal(days_held) / Decimal(365)).quantize(
            Decimal("0.0001")
        )
        assert entry.annual_dotation_mga == expected


def test_compute_annual_depreciation_chains_across_fiscal_years(asset_ledger) -> None:
    tenant, fy2026, fy2027, period2026, journal, immo_account = asset_ledger
    with use_tenant(tenant.id):
        asset = register_asset(
            tenant=tenant,
            category=AccAsset.CATEGORY_CORPORELLE,
            label="Machine Z",
            account=immo_account,
            acquisition_date=dt.date(2026, 1, 1),
            acquisition_value_mga=Decimal("1000000"),
            depreciation_method=AccAsset.METHOD_LINEAIRE,
            useful_life_years=5,
        )
        entry_2026 = compute_annual_depreciation(asset, fy2026)
        entry_2027 = compute_annual_depreciation(asset, fy2027)
        assert entry_2027.opening_accumulated_mga == entry_2026.closing_accumulated_mga
        assert entry_2027.closing_accumulated_mga == Decimal("400000.0000")


def test_compute_annual_depreciation_never_below_residual_value(asset_ledger) -> None:
    tenant, fy2026, fy2027, period2026, journal, immo_account = asset_ledger
    with use_tenant(tenant.id):
        asset = register_asset(
            tenant=tenant,
            category=AccAsset.CATEGORY_CORPORELLE,
            label="Machine presque amortie",
            account=immo_account,
            acquisition_date=dt.date(2020, 1, 1),
            acquisition_value_mga=Decimal("1000000"),
            depreciation_method=AccAsset.METHOD_LINEAIRE,
            useful_life_years=5,
            residual_value_mga=Decimal("100000"),
        )
        # Simule un cumul deja proche du plafond via une annuite anterieure.
        from apps.accounting.models import AccAssetDepreciation

        AccAssetDepreciation.objects.create(
            tenant=tenant,
            asset=asset,
            fiscal_year=AccFiscalYear.objects.create(
                tenant=tenant,
                code="FY2025",
                date_start=dt.date(2025, 1, 1),
                date_end=dt.date(2025, 12, 31),
            ),
            opening_accumulated_mga=Decimal("0"),
            annual_dotation_mga=Decimal("850000"),
            closing_accumulated_mga=Decimal("850000"),
        )
        entry = compute_annual_depreciation(asset, fy2026)
        # Base amortissable = 900000, deja 850000 cumules -> plafond restant
        # = 50000, meme si l'annuite pleine serait 180000.
        assert entry.annual_dotation_mga == Decimal("50000.0000")
        assert entry.closing_accumulated_mga == Decimal("900000.0000")


def test_compute_annual_depreciation_can_post_to_ledger(asset_ledger) -> None:
    tenant, fy2026, fy2027, period2026, journal, immo_account = asset_ledger
    with use_tenant(tenant.id):
        dotation_account = _make_account(
            tenant,
            code="6813",
            name="Dotations aux amortissements",
            account_class=6,
            type=AccAccount.TYPE_EXPENSE,
        )
        accumulated_account = _make_account(
            tenant,
            code="2833",
            name="Amortissements materiel",
            account_class=2,
            type=AccAccount.TYPE_ASSET,
        )
        asset = register_asset(
            tenant=tenant,
            category=AccAsset.CATEGORY_CORPORELLE,
            label="Machine postee",
            account=immo_account,
            acquisition_date=dt.date(2026, 1, 1),
            acquisition_value_mga=Decimal("1000000"),
            depreciation_method=AccAsset.METHOD_LINEAIRE,
            useful_life_years=5,
        )
        entry = compute_annual_depreciation(
            asset,
            fy2026,
            post=True,
            journal=journal,
            period=period2026,
            dotation_account=dotation_account,
            accumulated_depreciation_account=accumulated_account,
        )
        assert entry.move is not None
        assert entry.move.state == "posted"
        assert entry.move.total_debit == entry.move.total_credit == Decimal("200000.0000")


def test_compute_annual_depreciation_post_requires_accounts(asset_ledger) -> None:
    tenant, fy2026, fy2027, period2026, journal, immo_account = asset_ledger
    with use_tenant(tenant.id):
        asset = register_asset(
            tenant=tenant,
            category=AccAsset.CATEGORY_CORPORELLE,
            label="Machine incomplete",
            account=immo_account,
            acquisition_date=dt.date(2026, 1, 1),
            acquisition_value_mga=Decimal("1000000"),
            depreciation_method=AccAsset.METHOD_LINEAIRE,
            useful_life_years=5,
        )
        with pytest.raises(ValidationError):
            compute_annual_depreciation(asset, fy2026, post=True)


def test_dispose_asset_guards_double_disposal(asset_ledger) -> None:
    tenant, fy2026, fy2027, period2026, journal, immo_account = asset_ledger
    with use_tenant(tenant.id):
        asset = register_asset(
            tenant=tenant,
            category=AccAsset.CATEGORY_CORPORELLE,
            label="Machine a ceder",
            account=immo_account,
            acquisition_date=dt.date(2026, 1, 1),
            acquisition_value_mga=Decimal("1000000"),
            depreciation_method=AccAsset.METHOD_LINEAIRE,
            useful_life_years=5,
        )
        dispose_asset(
            asset, disposal_date=dt.date(2026, 6, 30), disposal_value_mga=Decimal("400000")
        )
        asset.refresh_from_db()
        assert asset.state == AccAsset.STATE_DISPOSED
        assert asset.movements.filter(movement_type="disposal").exists()

        with pytest.raises(ValidationError):
            dispose_asset(asset, disposal_date=dt.date(2026, 7, 1), disposal_value_mga=Decimal("0"))


def test_record_provision_movement_computes_closing_and_clamps_at_zero(asset_ledger) -> None:
    tenant, fy2026, fy2027, period2026, journal, immo_account = asset_ledger
    with use_tenant(tenant.id):
        provision_account = _make_account(
            tenant,
            code="151",
            name="Provisions pour litiges",
            account_class=1,
            type=AccAccount.TYPE_LIABILITY,
        )
        provision = record_provision_movement(
            tenant=tenant,
            nature="Litige client X",
            account=provision_account,
            fiscal_year=fy2026,
            opening_amount_mga=Decimal("100000"),
            dotation_mga=Decimal("50000"),
            reprise_mga=Decimal("30000"),
        )
        assert provision.closing_amount_mga == Decimal("120000")

        clamped = record_provision_movement(
            tenant=tenant,
            nature="Litige client Y",
            account=provision_account,
            fiscal_year=fy2026,
            opening_amount_mga=Decimal("10000"),
            reprise_mga=Decimal("50000"),
        )
        assert clamped.closing_amount_mga == Decimal("0")
