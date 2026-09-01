from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.partners.services.onboarding import create_partner
from apps.sales.services.orders import add_order_line, create_order
from apps.sales.services.quotations import add_quotation_line, create_quotation
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.fixture
def sales_screens_setup():
    tenant = Tenant.objects.create(code="UI-SALES", name="UI Sales Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="ui-sales@example.com", password="Str0ngPassw0rd!23")
        quotation = create_quotation(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        add_quotation_line(
            quotation, description="Ligne", qty=Decimal(1), unit_price=Decimal(1000), is_custom=True
        )
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        add_order_line(
            order, description="Ligne", qty=Decimal(1), unit_price=Decimal(1000), is_custom=True
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client, tenant, user, quotation, order


def test_quotation_list_screen_renders(sales_screens_setup) -> None:
    client, *_ = sales_screens_setup
    response = client.get("/sales/")
    assert response.status_code == 200


def test_quotation_create_screen(sales_screens_setup) -> None:
    client, *_ = sales_screens_setup
    response = client.post(
        "/sales/new/", {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())}
    )
    assert response.status_code == 302


def test_quotation_create_screen_embeds_partner_picker(sales_screens_setup) -> None:
    """UXR5 : le champ UUID brut est remplace par le composant UXR3
    (recherche + creation via popup), pas par un simple champ texte."""
    client, *_ = sales_screens_setup
    response = client.get("/sales/new/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "wh-partner-picker" in content
    assert 'name="partner_id"' in content
    assert 'id="partner_id_display"' in content
    assert "/partners/instant-picker/" in content
    assert "/partners/new/?embed=1" in content
    assert "Partenaire (UUID)" not in content


def test_quotation_create_screen_via_partner_picker_field(sales_screens_setup) -> None:
    """Bout en bout : un partenaire choisi via le picker (simule en postant
    le meme nom/valeur de champ que produirait le hidden input du
    composant) cree bien un devis reel."""
    client, tenant, *_ = sales_screens_setup
    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="Picker Client SARL", roles=["client"])
    response = client.post(
        "/sales/new/", {"partner_id": str(partner.id), "date": str(dt.date.today())}
    )
    assert response.status_code == 302


def test_quotation_detail_send_accept_convert_flow(sales_screens_setup) -> None:
    client, tenant, _user, quotation, _order = sales_screens_setup

    response = client.post(f"/sales/{quotation.id}/", {"action": "send"})
    assert response.status_code == 302

    response = client.post(f"/sales/{quotation.id}/", {"action": "accept"})
    assert response.status_code == 302

    detail = client.get(f"/sales/{quotation.id}/")
    assert b"Accepte" in detail.content

    response = client.post(f"/sales/{quotation.id}/", {"action": "convert_to_order"})
    assert response.status_code == 302
    assert response.url.startswith("/sales/orders/")

    with use_tenant(tenant.id):
        quotation.refresh_from_db()
        assert quotation.orders.count() == 1


def test_order_list_screen_renders_and_filters_by_state(sales_screens_setup) -> None:
    client, *_ = sales_screens_setup
    response = client.get("/sales/orders/")
    assert response.status_code == 200
    response = client.get("/sales/orders/?state=draft")
    assert response.status_code == 200


def test_order_create_screen(sales_screens_setup) -> None:
    client, *_ = sales_screens_setup
    response = client.post(
        "/sales/orders/new/", {"partner_id": str(uuid.uuid4()), "date": str(dt.date.today())}
    )
    assert response.status_code == 302


def test_order_create_screen_embeds_partner_picker(sales_screens_setup) -> None:
    """UXR5 : meme traitement que le devis pour l'ecran de creation de
    commande."""
    client, *_ = sales_screens_setup
    response = client.get("/sales/orders/new/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "wh-partner-picker" in content
    assert 'name="partner_id"' in content
    assert 'id="partner_id_display"' in content
    assert "/partners/instant-picker/" in content
    assert "/partners/new/?embed=1" in content
    assert "Partenaire (UUID)" not in content


def test_order_create_screen_via_partner_picker_field(sales_screens_setup) -> None:
    """Bout en bout : un partenaire choisi via le picker cree bien une
    commande reelle."""
    client, tenant, *_ = sales_screens_setup
    with use_tenant(tenant.id):
        partner = create_partner(tenant=tenant, name="Picker Order SARL", roles=["client"])
    response = client.post(
        "/sales/orders/new/", {"partner_id": str(partner.id), "date": str(dt.date.today())}
    )
    assert response.status_code == 302


def test_order_detail_full_workflow_no_full_reload_uses_redirect(sales_screens_setup) -> None:
    """Chaque action de bandeau de workflow repond par une redirection
    (302) vers la meme fiche detail — jamais un re-rendu de page complete
    depuis un formulaire d'action, meme convention que
    `tests/ui/test_mrp_screens.py`."""
    client, tenant, _user, _quotation, order = sales_screens_setup

    response = client.post(f"/sales/orders/{order.id}/", {"action": "confirm"})
    assert response.status_code == 302

    detail = client.get(f"/sales/orders/{order.id}/")
    assert b"Confirme" in detail.content

    response = client.post(f"/sales/orders/{order.id}/", {"action": "start_preparation"})
    assert response.status_code == 302

    response = client.post(f"/sales/orders/{order.id}/", {"action": "deliver_full"})
    assert response.status_code == 302

    with use_tenant(tenant.id):
        order.refresh_from_db()
        assert order.state == "delivered"


def test_order_detail_cancel_requires_reason(sales_screens_setup) -> None:
    client, tenant, _user, _quotation, order = sales_screens_setup
    response = client.post(f"/sales/orders/{order.id}/", {"action": "cancel", "reason": ""})
    assert response.status_code == 200  # re-rendu avec erreur, pas de redirect
    assert b"motif" in response.content.lower() or b"error" in response.content.lower()

    response = client.post(
        f"/sales/orders/{order.id}/", {"action": "cancel", "reason": "Client desiste"}
    )
    assert response.status_code == 302
    with use_tenant(tenant.id):
        order.refresh_from_db()
        assert order.state == "cancelled"


def test_margin_column_hidden_for_plain_commercial_screen(sales_screens_setup) -> None:
    """RG-SAL-5 volet ecran (cf. `apps/sales/tests/test_margin_masking.py`
    pour la couverture complete role-par-role) : sans role de pilotage, la
    fiche commande ne rend jamais la colonne Marge."""
    client, tenant, _user, _quotation, order = sales_screens_setup
    from apps.core.tests.utils import grant_role

    commercial = User.objects.create_user(
        email="plain-commercial@example.com", password="Str0ngPassw0rd!23"
    )
    with use_tenant(tenant.id):
        grant_role(commercial, "commercial")
    other_client = Client()
    other_client.force_login(commercial)
    session = other_client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = other_client.get(f"/sales/orders/{order.id}/")
    assert response.status_code == 200
    assert b"Marge" not in response.content


def test_reports_index_renders(sales_screens_setup) -> None:
    client, *_ = sales_screens_setup
    response = client.get("/sales/reports/")
    assert response.status_code == 200


def test_config_recurrences_screen_renders(sales_screens_setup) -> None:
    client, *_ = sales_screens_setup
    response = client.get("/sales/config/recurrences/")
    assert response.status_code == 200
