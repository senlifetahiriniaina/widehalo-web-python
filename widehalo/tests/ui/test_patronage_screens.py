from __future__ import annotations

from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.patronage.models import PatSizeChart
from apps.patronage.services.patterns import (
    add_pattern_piece,
    create_pattern,
    generate_piece_geometry,
)
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def patronage_screens_setup():
    tenant = Tenant.objects.create(code="UI-PAT", name="UI Patronage Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="ui-pat@example.com", password="Str0ngPassw0rd!23")
        size_chart = PatSizeChart.objects.create(
            tenant=tenant,
            code="TSHIRT-UI",
            name="T-shirt UI",
            garment_type=PatSizeChart.GARMENT_TSHIRT,
            sizes=["S", "M"],
            base_size="S",
        )
        pattern = create_pattern(
            tenant=tenant, code="PAT-UI", name="T-shirt UI", size_chart=size_chart
        )
        piece = add_pattern_piece(pattern, code="devant", name="Devant")
        generate_piece_geometry(
            piece,
            size="S",
            graded_measurements={"tour_poitrine": Decimal(90), "longueur": Decimal(65)},
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, size_chart, pattern


def test_pattern_create_screen(patronage_screens_setup) -> None:
    client, _tenant, size_chart, _pattern = patronage_screens_setup
    response = client.post(
        "/patronage/new/",
        {"code": "PAT-UI-2", "name": "Nouveau patron", "size_chart_id": str(size_chart.id)},
    )
    assert response.status_code == 302


def test_pattern_detail_shows_pieces(patronage_screens_setup) -> None:
    client, _tenant, _size_chart, pattern = patronage_screens_setup
    response = client.get(f"/patronage/{pattern.id}/")
    assert response.status_code == 200
    assert b"Devant" in response.content


def test_pattern_list_screen_renders(patronage_screens_setup) -> None:
    client, _tenant, _size_chart, _pattern = patronage_screens_setup
    response = client.get("/patronage/")
    assert response.status_code == 200
