from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpCri, MrpWorkcenter, MrpWorkshop
from apps.patronage.models import PatSizeChart
from apps.patronage.services.patterns import (
    add_pattern_piece,
    create_pattern,
    generate_piece_geometry,
)
from apps.patronage.services.production_link import report_conformity_incident
from apps.patronage.services.tech_pack import generate_tech_pack

pytestmark = pytest.mark.django_db


@pytest.fixture
def tech_pack_setup():
    tenant = Tenant.objects.create(code="PAT-TECH", name="Patronage Tech Pack Tenant")
    with use_tenant(tenant.id):
        size_chart = PatSizeChart.objects.create(
            tenant=tenant,
            code="TSHIRT-U",
            name="T-shirt unisexe",
            garment_type=PatSizeChart.GARMENT_TSHIRT,
            sizes=["S", "M"],
            base_size="S",
        )
        pattern = create_pattern(
            tenant=tenant, code="PAT-1", name="T-shirt basique", size_chart=size_chart
        )
        piece = add_pattern_piece(pattern, code="devant", name="Devant", notes="Coudre epaules")
        generate_piece_geometry(
            piece,
            size="S",
            graded_measurements={"tour_poitrine": Decimal(90), "longueur": Decimal(65)},
        )
        workshop = MrpWorkshop.objects.create(tenant=tenant, code="ATL-1", name="Atelier")
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant,
            workshop=workshop,
            code="C1",
            name="Couture",
            type=MrpWorkcenter.TYPE_SEWING,
        )
        return tenant, pattern, workcenter


def test_generate_tech_pack_stores_pdf_document(tech_pack_setup) -> None:
    tenant, pattern, _workcenter = tech_pack_setup
    with use_tenant(tenant.id):
        tech_pack = generate_tech_pack(pattern)
        assert tech_pack.version == pattern.version
        assert tech_pack.document.mime_type == "application/pdf"
        assert tech_pack.document.size > 0


def test_report_conformity_incident_creates_cri_linked_to_pattern(tech_pack_setup) -> None:
    tenant, pattern, workcenter = tech_pack_setup
    with use_tenant(tenant.id):
        cri_id = report_conformity_incident(
            pattern,
            workcenter_id=workcenter.id,
            description="Couture epaule mal executee",
            cause="Instruction ambigue",
        )
        cri = MrpCri.objects.get(id=cri_id)
        assert cri.pattern_id == pattern.id
        assert cri.type == MrpCri.TYPE_QUALITY_INCIDENT
