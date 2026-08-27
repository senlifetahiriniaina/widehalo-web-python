"""A11 — ACC-DCOM1 (`services/dcom.py`, `services/reports.py::dcom_report`)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.accounting.models import (
    AccAccount,
    AccDcomDeclaration,
    AccFiscalYear,
    AccJournal,
    AccPeriod,
)
from apps.accounting.services.dcom import generate_dcom_declaration
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.accounting.services.reports import dcom_report
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _make_account(tenant, *, code, name, account_class, type):
    return AccAccount.objects.create(
        tenant=tenant, code=code, name=name, account_class=account_class, type=type
    )


@pytest.fixture
def dcom_ledger():
    tenant = Tenant.objects.create(code="ACC-DCOM", name="DCOM Tenant")
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
        journal = AccJournal.objects.create(
            tenant=tenant, code="OD", name="OD", type=AccJournal.TYPE_MISC, sequence_prefix="OD"
        )
        purchase_account = _make_account(
            tenant, code="601", name="Achats", account_class=6, type=AccAccount.TYPE_EXPENSE
        )
        supplier_account = _make_account(
            tenant, code="401", name="Fournisseurs", account_class=4, type=AccAccount.TYPE_PAYABLE
        )
        partner_id = uuid.uuid4()

        # Meme convention que `services/invoices.py::create_invoice` : le
        # `partner_id` n'est porte que par la ligne tiers (creance/dette),
        # jamais par la ligne de contrepartie (achat/vente) — sans quoi
        # chaque transaction remonterait en double au DCOM (une fois par
        # classification de compte).
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 10)
        )
        add_line(move, account=purchase_account, label="Achat matiere", debit=Decimal("500000"))
        add_line(
            move,
            account=supplier_account,
            label="Achat matiere",
            credit=Decimal("500000"),
            partner_id=partner_id,
        )
        post_move(move)

        # Ligne SANS tiers (partner_id nul) : ne doit jamais apparaitre au
        # rapport DCOM (RG DCOM implicite : ne concerne que les tiers).
        draft_account = purchase_account
        no_partner_move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 15)
        )
        add_line(no_partner_move, account=draft_account, label="Sans tiers", debit=Decimal("10000"))
        add_line(
            no_partner_move, account=supplier_account, label="Sans tiers", credit=Decimal("10000")
        )
        post_move(no_partner_move)

        return {"tenant": tenant, "fiscal_year": fiscal_year, "partner_id": partner_id}


def test_generate_dcom_declaration_aggregates_by_partner_and_pcg_class(dcom_ledger) -> None:
    fiscal_year = dcom_ledger["fiscal_year"]
    partner_id = dcom_ledger["partner_id"]
    with use_tenant(dcom_ledger["tenant"].id):
        declaration = generate_dcom_declaration(fiscal_year)
        assert declaration.reference
        assert declaration.total_amount_mga == Decimal("500000.0000")
        lines = list(declaration.lines.all())
        assert len(lines) == 1
        assert lines[0].partner_id == partner_id
        assert lines[0].classification == "tiers"
        assert lines[0].amount_mga == Decimal("500000.0000")


def test_generate_dcom_declaration_is_idempotent_per_fiscal_year(dcom_ledger) -> None:
    fiscal_year = dcom_ledger["fiscal_year"]
    with use_tenant(dcom_ledger["tenant"].id):
        first = generate_dcom_declaration(fiscal_year)
        second = generate_dcom_declaration(fiscal_year)
        assert first.id == second.id
        assert AccDcomDeclaration.objects.filter(fiscal_year=fiscal_year).count() == 1
        assert second.lines.count() == 1


def test_dcom_report_resolves_partner_display_name(dcom_ledger, monkeypatch) -> None:
    fiscal_year = dcom_ledger["fiscal_year"]
    with use_tenant(dcom_ledger["tenant"].id):
        declaration = generate_dcom_declaration(fiscal_year)

        monkeypatch.setattr(
            "apps.partners.services.public.get_partner_display_name", lambda partner_id: "ACME SARL"
        )
        rows = dcom_report(declaration)
        assert len(rows) == 1
        assert rows[0]["partner_name"] == "ACME SARL"
        assert rows[0]["classification"] == "tiers"
        assert rows[0]["amount_mga"] == Decimal("500000.0000")
