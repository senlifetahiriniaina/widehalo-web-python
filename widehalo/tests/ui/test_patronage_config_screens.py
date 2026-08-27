from __future__ import annotations

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.patronage.models import PatGradingRule, PatMeasurementPoint, PatSizeChart
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def patronage_config_setup():
    tenant = Tenant.objects.create(code="UI-PAT-CFG", name="UI Patronage Config Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="ui-pat-cfg@example.com", password="Str0ngPassw0rd!23"
        )
        size_chart = PatSizeChart.objects.create(
            tenant=tenant,
            code="TSHIRT-CFG",
            name="T-shirt Config",
            garment_type=PatSizeChart.GARMENT_TSHIRT,
            sizes=["S", "M", "L"],
            base_size="M",
        )
        measurement_point = PatMeasurementPoint.objects.create(
            tenant=tenant,
            code="TOUR-POITRINE",
            name="Tour de poitrine",
            unit=PatMeasurementPoint.UNIT_CM,
            category=PatMeasurementPoint.CATEGORY_CIRCUMFERENCE,
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, size_chart, measurement_point


def test_config_index_screen(patronage_config_setup) -> None:
    client, *_ = patronage_config_setup
    response = client.get("/patronage/config/")
    assert response.status_code == 200


def test_create_size_chart_via_screen(patronage_config_setup) -> None:
    client, tenant, *_ = patronage_config_setup
    response = client.post(
        "/patronage/config/size-charts/",
        {
            "code": "PANTALON-CFG",
            "name": "Pantalon Config",
            "garment_type": "pantalon",
            "sizes": "36,38,40",
            "base_size": "38",
        },
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        size_chart = PatSizeChart.objects.get(code="PANTALON-CFG")
        assert size_chart.sizes == ["36", "38", "40"]


def test_add_measurement_point_and_value_to_size_chart(patronage_config_setup) -> None:
    client, tenant, size_chart, measurement_point = patronage_config_setup

    response = client.post(
        f"/patronage/config/size-charts/{size_chart.id}/",
        {
            "action": "add_measurement_point",
            "code": "LONGUEUR-DOS",
            "name": "Longueur dos",
            "unit": "cm",
            "category": "longueur",
        },
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        assert PatMeasurementPoint.objects.filter(code="LONGUEUR-DOS").exists()

    response = client.post(
        f"/patronage/config/size-charts/{size_chart.id}/",
        {
            "action": "add_value",
            "measurement_point_id": str(measurement_point.id),
            "size": "M",
            "value": "92.5",
        },
    )
    assert response.status_code == 302

    detail = client.get(f"/patronage/config/size-charts/{size_chart.id}/")
    assert detail.status_code == 200
    # Le rendu localise en francais utilise la virgule comme separateur
    # decimal (`USE_THOUSAND_SEPARATOR`/`USE_L10N`) : "92,50" et non "92.5".
    assert b"92,50" in detail.content
    with use_tenant(tenant.id):
        assert size_chart.values.filter(measurement_point=measurement_point, size="M").exists()


def test_create_grading_rule_via_screen(patronage_config_setup) -> None:
    client, tenant, size_chart, measurement_point = patronage_config_setup
    response = client.post(
        "/patronage/config/grading-rules/",
        {
            "size_chart_id": str(size_chart.id),
            "measurement_point_id": str(measurement_point.id),
            "mode": "increment_fixe",
            "value": "1.5",
            "from_size": "S",
            "to_size": "M",
        },
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        assert PatGradingRule.objects.filter(
            size_chart=size_chart, measurement_point=measurement_point
        ).exists()
