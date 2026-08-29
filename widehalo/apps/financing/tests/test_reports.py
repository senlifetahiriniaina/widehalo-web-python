from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.reports_registry import get_registered_report
from apps.core.tests.utils import use_tenant
from apps.financing.models import FinGuarantee
from apps.financing.services.credoc import create_credoc
from apps.financing.services.forecast import add_scenario_line, create_scenario
from apps.financing.services.guarantees import add_guarantee
from apps.financing.services.loan_applications import (
    add_financing_plan_line,
    create_loan_application,
)
from apps.financing.services.reports import generate_credoc_pdf, generate_dossier_pdf

pytestmark = pytest.mark.django_db


def test_fin_dossier_and_fin_credoc_are_registered_render_pdf_only() -> None:
    dossier_report = get_registered_report("FIN-DOSSIER")
    credoc_report = get_registered_report("FIN-CREDOC")
    assert dossier_report is not None
    assert dossier_report.supports_pdf() is True
    assert dossier_report.supports_rows() is False
    assert credoc_report is not None
    assert credoc_report.supports_pdf() is True
    assert credoc_report.supports_rows() is False


def test_generate_dossier_pdf_assembles_all_sections() -> None:
    tenant = Tenant.objects.create(code="FIN-RPT1", name="Financing Report Tenant 1")
    with use_tenant(tenant.id):
        application = create_loan_application(
            tenant,
            type="investissement_lt",
            amount_requested_mga=Decimal("50000000"),
            duration_months=48,
            bank_name="Banque Test",
        )
        add_financing_plan_line(application, source="fonds_propres", amount_mga=Decimal("15000000"))
        add_financing_plan_line(
            application, source="emprunt_sollicite", amount_mga=Decimal("35000000")
        )
        add_guarantee(
            application,
            type=FinGuarantee.GUARANTEE_TYPE_MORTGAGE,
            estimated_value_mga=Decimal("60000000"),
        )
        scenario = create_scenario(
            tenant,
            name="Scenario dossier",
            period_start=dt.date(2026, 1, 1),
            period_end=dt.date(2026, 12, 31),
            loan_application=application,
        )
        add_scenario_line(
            scenario,
            statement_type="income_statement",
            label="Chiffre d'affaires previsionnel",
            period="2026-01",
            amount_mga=Decimal("8000000"),
        )

        pdf_bytes = generate_dossier_pdf(application, scenario=scenario)

        assert pdf_bytes.startswith(b"%PDF")


def test_generate_dossier_pdf_without_optional_sections() -> None:
    tenant = Tenant.objects.create(code="FIN-RPT2", name="Financing Report Tenant 2")
    with use_tenant(tenant.id):
        application = create_loan_application(
            tenant,
            type="fonctionnement",
            amount_requested_mga=Decimal("5000000"),
            duration_months=12,
        )
        pdf_bytes = generate_dossier_pdf(application)
        assert pdf_bytes.startswith(b"%PDF")


def test_generate_credoc_pdf() -> None:
    tenant = Tenant.objects.create(code="FIN-RPT3", name="Financing Report Tenant 3")
    with use_tenant(tenant.id):
        credoc = create_credoc(
            tenant,
            purchase_order_id=uuid.uuid4(),
            bank="Banque emettrice",
            beneficiary="Fournisseur import",
            amount_mga=Decimal("25000000"),
            validity_date=dt.date(2026, 12, 31),
            documents_required=["Facture commerciale", "Connaissement (B/L)"],
        )
        pdf_bytes = generate_credoc_pdf(credoc)
        assert pdf_bytes.startswith(b"%PDF")
