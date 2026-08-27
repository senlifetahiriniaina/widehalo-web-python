"""A12 — ACC-IS/ACC-IR (`services/tax_returns.py`) et ACC-EXPORT-FISC1
(`services/fiscal_export.py`)."""

from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal

import pdfplumber
import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccPeriod
from apps.accounting.services.fiscal_export import CANEVAS_NOTES, export_canevas_notes
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.accounting.services.tax_returns import generate_liasse_ir, generate_liasse_is
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _make_account(tenant, *, code, name, account_class, type, is_current=True):
    return AccAccount.objects.create(
        tenant=tenant,
        code=code,
        name=name,
        account_class=account_class,
        type=type,
        is_current=is_current,
    )


def _small_ledger(fiscal_regime: str):
    tenant = Tenant.objects.create(
        code="ACC-A12", name="Accounting A12 Tenant", fiscal_regime=fiscal_regime
    )
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
            tenant=tenant,
            code="OD",
            name="Operations diverses",
            type=AccJournal.TYPE_MISC,
            sequence_prefix="OD",
        )
        receivable = _make_account(
            tenant, code="411", name="Clients", account_class=4, type=AccAccount.TYPE_RECEIVABLE
        )
        income = _make_account(
            tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
        bank = _make_account(
            tenant, code="512", name="Banques", account_class=5, type=AccAccount.TYPE_BANK
        )
        equity = _make_account(
            tenant,
            code="101",
            name="Capital social",
            account_class=1,
            type=AccAccount.TYPE_EQUITY,
            is_current=False,
        )

        date = dt.date(2026, 1, 15)
        move1 = create_draft_move(tenant=tenant, journal=journal, period=period, date=date)
        add_line(move1, account=receivable, label="Vente client", debit=Decimal(5000))
        add_line(move1, account=income, label="Ventes", credit=Decimal(5000))
        post_move(move1)

        move2 = create_draft_move(tenant=tenant, journal=journal, period=period, date=date)
        add_line(move2, account=bank, label="Apport capital", debit=Decimal(10000))
        add_line(move2, account=equity, label="Capital", credit=Decimal(10000))
        post_move(move2)

        return tenant, fiscal_year


@pytest.fixture
def synthetic_ledger():
    return _small_ledger(Tenant.FISCAL_REGIME_SYNTHETIC)


@pytest.fixture
def real_ledger():
    return _small_ledger(Tenant.FISCAL_REGIME_REAL_WITH_VAT)


def test_generate_liasse_is_returns_a_pdf_with_all_sections(synthetic_ledger) -> None:
    tenant, fiscal_year = synthetic_ledger
    with use_tenant(tenant.id):
        pdf_bytes = generate_liasse_is(fiscal_year)
        assert pdf_bytes.startswith(b"%PDF")
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        assert "Bilan" in text
        assert "Compte de resultat par nature" in text
        assert "Compte de resultat par fonction" in text
        assert "flux de tresorerie" in text


def test_generate_liasse_is_rejects_a_real_regime_tenant(real_ledger) -> None:
    tenant, fiscal_year = real_ledger
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        generate_liasse_is(fiscal_year)


def test_generate_liasse_ir_returns_a_pdf_with_all_sections_and_annexes(real_ledger) -> None:
    tenant, fiscal_year = real_ledger
    with use_tenant(tenant.id):
        pdf_bytes = generate_liasse_ir(fiscal_year)
        assert pdf_bytes.startswith(b"%PDF")
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        assert "Bilan" in text
        assert "Compte de resultat par nature" in text
        assert "Compte de resultat par fonction" in text
        assert "flux de tresorerie" in text
        assert "capitaux propres" in text
        assert "Annexes fiscales" in text
        assert "actif immobilise" in text


def test_generate_liasse_ir_rejects_a_synthetic_regime_tenant(synthetic_ledger) -> None:
    tenant, fiscal_year = synthetic_ledger
    with use_tenant(tenant.id), pytest.raises(ValidationError):
        generate_liasse_ir(fiscal_year)


def test_canevas_notes_registry_covers_the_minimum_expected_reports() -> None:
    notes = export_canevas_notes()
    for code in ("ACC-TVA", "ACC-DCOM", "ACC-IRSA", "ACC-IS", "ACC-IR"):
        assert code in notes
        assert notes[code]  # non vide

    # ACC-IRSA documente explicitement l'absence de module paie plutot que
    # de fabriquer un rapport qui n'existe pas encore dans ce codebase.
    assert "module paie" in notes["ACC-IRSA"] or "payroll" in notes["ACC-IRSA"]

    # `export_canevas_notes()` retourne une copie, pas la reference vivante
    # au registre module-level.
    notes["ACC-IS"] = "mutated"
    assert CANEVAS_NOTES["ACC-IS"] != "mutated"
