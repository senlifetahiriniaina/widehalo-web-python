from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.patronage.models import PatMeasurementPoint, PatSizeChart, PatSizeChartValue
from apps.patronage.services.consumption import compute_consumption, compute_marker
from apps.patronage.services.patterns import (
    add_pattern_piece,
    create_pattern,
    generate_piece_geometry,
    new_pattern_version,
)
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def patronage_reports_setup():
    tenant = Tenant.objects.create(code="UI-PAT-RPT", name="UI Patronage Reports Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="ui-pat-rpt@example.com", password="Str0ngPassw0rd!23"
        )
        material_id = uuid.uuid4()
        size_chart = PatSizeChart.objects.create(
            tenant=tenant,
            code="TSHIRT-RPT",
            name="T-shirt RPT",
            garment_type=PatSizeChart.GARMENT_TSHIRT,
            sizes=["S", "M"],
            base_size="S",
        )
        chest = PatMeasurementPoint.objects.create(
            tenant=tenant, code="tour_poitrine", name="Tour de poitrine"
        )
        PatSizeChartValue.objects.create(
            tenant=tenant,
            size_chart=size_chart,
            measurement_point=chest,
            size="S",
            value=Decimal(90),
        )
        pattern = create_pattern(
            tenant=tenant, code="PAT-RPT", name="T-shirt RPT", size_chart=size_chart
        )
        piece = add_pattern_piece(
            pattern, code="devant", name="Devant", material_variant_id=material_id
        )
        generate_piece_geometry(
            piece,
            size="S",
            graded_measurements={"tour_poitrine": Decimal(90), "longueur": Decimal(65)},
        )
        compute_consumption(
            pattern, size="S", material_variant_id=material_id, width_cm=Decimal(150)
        )
        compute_marker(
            pattern,
            material_variant_id=material_id,
            fabric_width_cm=Decimal(150),
            size_ratio={"S": 2},
        )
        new_pattern_version(pattern)

    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, pattern


def test_report_measurements(patronage_reports_setup) -> None:
    client, _tenant, pattern = patronage_reports_setup
    response = client.get(f"/patronage/{pattern.id}/reports/measurements/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert b"measurement_point" in response.content


def test_report_consumption(patronage_reports_setup) -> None:
    client, _tenant, pattern = patronage_reports_setup
    response = client.get(f"/patronage/{pattern.id}/reports/consumption/", {"format": "csv"})
    assert response.status_code == 200
    assert response["Content-Type"] == "text/csv"
    assert b"length_m" in response.content


def test_report_marker(patronage_reports_setup) -> None:
    client, _tenant, pattern = patronage_reports_setup
    response = client.get(f"/patronage/{pattern.id}/reports/marker/", {"format": "json"})
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert b"efficiency_pct" in response.content


def test_report_versions(patronage_reports_setup) -> None:
    client, _tenant, pattern = patronage_reports_setup
    response = client.get(f"/patronage/{pattern.id}/reports/versions/", {"format": "xlsx"})
    assert response.status_code == 200
    assert (
        response["Content-Type"]
        == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert len(response.content) > 0


def test_reports_require_login(patronage_reports_setup) -> None:
    _client, _tenant, pattern = patronage_reports_setup
    anon_client = Client()
    response = anon_client.get(f"/patronage/{pattern.id}/reports/measurements/")
    assert response.status_code == 302
