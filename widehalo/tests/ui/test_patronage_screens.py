from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpBomLine
from apps.mrp.services.bom import activate_bom, create_bom
from apps.patronage.models import PatSizeChart
from apps.patronage.services.consumption import compute_consumption
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


@pytest.fixture
def patronage_consumption_screens_setup():
    tenant = Tenant.objects.create(code="UI-PAT-CONS", name="UI Patronage Consumption Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="ui-pat-cons@example.com", password="Str0ngPassw0rd!23"
        )
        product_id = uuid.uuid4()
        material_id = uuid.uuid4()
        size_chart = PatSizeChart.objects.create(
            tenant=tenant,
            code="TSHIRT-UI-C",
            name="T-shirt UI consommation",
            garment_type=PatSizeChart.GARMENT_TSHIRT,
            sizes=["S", "M"],
            base_size="S",
        )
        pattern = create_pattern(
            tenant=tenant,
            code="PAT-UI-C",
            name="T-shirt UI consommation",
            size_chart=size_chart,
            product_template_id=product_id,
        )
        piece = add_pattern_piece(
            pattern, code="devant", name="Devant", material_variant_id=material_id
        )
        generate_piece_geometry(
            piece,
            size="M",
            graded_measurements={"tour_poitrine": Decimal(100), "longueur": Decimal(70)},
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, pattern, piece, material_id, product_id


def test_add_piece_and_generate_geometry_via_ui(patronage_screens_setup) -> None:
    client, tenant, _size_chart, pattern = patronage_screens_setup
    response = client.post(
        f"/patronage/{pattern.id}/",
        {"action": "add_piece", "code": "dos", "name": "Dos", "qty_per_garment": "1"},
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        piece = pattern.pieces.get(code="dos")

    response = client.post(
        f"/patronage/{pattern.id}/",
        {
            "action": "generate_geometry",
            "piece_id": str(piece.id),
            "size": "M",
            "tour_poitrine": "90",
            "longueur": "65",
        },
    )
    assert response.status_code == 302

    with use_tenant(tenant.id):
        assert piece.geometries.filter(size="M").exists()


def test_compute_consumption_and_marker_via_ui(patronage_consumption_screens_setup) -> None:
    client, _tenant, pattern, _piece, material_id, _product_id = patronage_consumption_screens_setup

    response = client.post(
        f"/patronage/{pattern.id}/",
        {
            "action": "compute_consumption",
            "size": "M",
            "material_variant_id": str(material_id),
            "width_cm": "150",
            "waste_pct": "0",
        },
    )
    assert response.status_code == 302
    detail = client.get(f"/patronage/{pattern.id}/")
    assert b"Consommation matiere" in detail.content

    response = client.post(
        f"/patronage/{pattern.id}/",
        {
            "action": "compute_marker",
            "material_variant_id": str(material_id),
            "fabric_width_cm": "150",
            "size_ratio": "M:2",
        },
    )
    assert response.status_code == 302
    detail = client.get(f"/patronage/{pattern.id}/")
    assert b"Plan de coupe" in detail.content


def test_push_to_bom_and_revert_via_ui(patronage_consumption_screens_setup) -> None:
    client, tenant, pattern, _piece, material_id, _product_id = patronage_consumption_screens_setup
    with use_tenant(tenant.id):
        compute_consumption(
            pattern, size="M", material_variant_id=material_id, width_cm=Decimal(150)
        )
        bom = create_bom(tenant=tenant, code="BOM-UI", product_template_id=uuid.uuid4())
        line = MrpBomLine.objects.create(
            tenant=tenant,
            bom=bom,
            component_template_id=uuid.uuid4(),
            component_variant_id=material_id,
        )

    response = client.post(
        f"/patronage/{pattern.id}/",
        {"action": "push_to_bom", "bom_id": str(bom.id), "material_variant_id": str(material_id)},
    )
    assert response.status_code == 302
    line.refresh_from_db()
    assert "M" in line.qty_by_size

    response = client.post(
        f"/patronage/{pattern.id}/",
        {
            "action": "revert_push_to_bom",
            "bom_id": str(bom.id),
            "material_variant_id": str(material_id),
        },
    )
    assert response.status_code == 302
    line.refresh_from_db()
    assert line.qty_by_size == {}


def test_push_to_bom_on_active_bom_shows_error_via_ui(
    patronage_consumption_screens_setup,
) -> None:
    client, tenant, pattern, _piece, material_id, _product_id = patronage_consumption_screens_setup
    with use_tenant(tenant.id):
        compute_consumption(
            pattern, size="M", material_variant_id=material_id, width_cm=Decimal(150)
        )
        bom = create_bom(tenant=tenant, code="BOM-UI-ACTIVE", product_template_id=uuid.uuid4())
        MrpBomLine.objects.create(
            tenant=tenant,
            bom=bom,
            component_template_id=uuid.uuid4(),
            component_variant_id=material_id,
        )
        activate_bom(bom)

    response = client.post(
        f"/patronage/{pattern.id}/",
        {"action": "push_to_bom", "bom_id": str(bom.id), "material_variant_id": str(material_id)},
    )
    assert response.status_code == 200
    assert b"form-error" in response.content


def test_tech_pack_download_via_session(patronage_screens_setup) -> None:
    client, _tenant, _size_chart, pattern = patronage_screens_setup
    detail = client.get(f"/patronage/{pattern.id}/")
    assert detail.status_code == 200
    assert f"/patronage/{pattern.id}/tech-pack.pdf".encode() in detail.content
    assert b"/api/v1/patronage" not in detail.content

    response = client.get(f"/patronage/{pattern.id}/tech-pack.pdf")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_new_version_shows_impacted_boms_preview(patronage_consumption_screens_setup) -> None:
    client, tenant, pattern, _piece, _material_id, product_id = patronage_consumption_screens_setup
    with use_tenant(tenant.id):
        bom = create_bom(tenant=tenant, code="BOM-UI-IMPACT", product_template_id=product_id)
        activate_bom(bom)

    response = client.get(f"/patronage/{pattern.id}/")
    assert response.status_code == 200
    assert b"BOM-UI-IMPACT" in response.content

    response = client.post(f"/patronage/{pattern.id}/", {"action": "new_version"})
    assert response.status_code == 302

    with use_tenant(tenant.id):
        new_version = pattern.versions.get()
        assert new_version.version == pattern.version + 1
