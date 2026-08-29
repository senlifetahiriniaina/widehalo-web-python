from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.services.reports_registry import get_registered_report
from apps.core.tests.utils import use_tenant
from apps.feasibility.services.reports import generate_feasibility_study_pdf
from apps.feasibility.services.simulation import add_study_line, create_study, simulate_study_line

pytestmark = pytest.mark.django_db


def test_fea_study_is_registered_render_pdf_only() -> None:
    report = get_registered_report("FEA-STUDY")
    assert report is not None
    assert report.supports_pdf() is True
    assert report.supports_rows() is False


def test_generate_feasibility_study_pdf_is_a_non_empty_pdf() -> None:
    tenant = Tenant.objects.create(code="FEA-RPT1", name="Feasibility Report Tenant 1")
    with use_tenant(tenant.id):
        study = create_study(tenant, name="Etude rapport PDF", sector_code="textile")
        line = add_study_line(
            study,
            hypothetical_spec={"name": "Produit rapport"},
            assumed_qty=Decimal(10),
            assumed_unit_price_mga=Decimal(5000),
            cost_breakdown={
                "material": Decimal(2000),
                "labor": Decimal(500),
                "overhead": Decimal(100),
                "total": Decimal(2600),
            },
        )
        simulate_study_line(line)

        pdf_bytes = generate_feasibility_study_pdf(study)
        assert pdf_bytes.startswith(b"%PDF")
        assert len(pdf_bytes) > 0
