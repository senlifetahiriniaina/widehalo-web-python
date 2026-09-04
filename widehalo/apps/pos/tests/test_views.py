"""Écrans HTMX du module `pos` — rendu réel (django-cotton, boucles de
gabarit) plutôt qu'un simple test de service, seule façon de détecter une
erreur de gabarit (balise mal fermée, filtre/tag inexistant, variable de
contexte manquante) avant une session manuelle."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.test import Client

from apps.accounting.models import AccTax
from apps.accounting.tests.factories import AccTaxFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.pos.models import PosOrderLine
from apps.pos.services.orders import add_line, add_payment, create_draft_order, validate_order
from apps.pos.services.sessions import open_session
from apps.pos.tests.factories import PosPaymentMethodFactory, PosRegisterFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def web_pos():
    tenant = Tenant.objects.create(code="POS-WEB", name="POS Web Tenant")
    user = User.objects.create_user(email="pos-web@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "caissier")
    return tenant, user


def _client_for(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_back_office_index_tabs_render(web_pos) -> None:
    # `caissier` (déjà accordé par le fixture `web_pos`) suffit : accès
    # app-level complet à `pos` (view/add/change), même granularité que
    # tous les autres rôles (cf. docstring de `rbac_policy.
    # ROLE_APP_PERMISSIONS`) — jamais `admin`/`direction` ici : ces 2
    # rôles exigent le second facteur (`CORE_MFA_REQUIRED_ROLES`), qui
    # redirigerait vers `/mfa/` avant tout autre écran, hors périmètre de
    # ce test d'écran.
    tenant, user = web_pos
    with use_tenant(tenant.id):
        PosRegisterFactory(tenant=tenant)
        PosPaymentMethodFactory(tenant=tenant)
    client = _client_for(tenant, user)

    for path in ("/pos/registers/", "/pos/payment-methods/", "/pos/sessions/", "/pos/sync-log/"):
        response = client.get(path, HTTP_X_TENANT_ID=str(tenant.id))
        assert response.status_code == 200, path


def test_sale_screen_renders_the_open_session_form_when_no_session_is_open(web_pos) -> None:
    tenant, user = web_pos
    with use_tenant(tenant.id):
        PosRegisterFactory(tenant=tenant)
    client = _client_for(tenant, user)

    response = client.get("/pos/sale/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 200
    assert b"Ouvrir la session" in response.content


def test_sale_screen_renders_the_cart_when_a_session_is_open(web_pos) -> None:
    tenant, user = web_pos
    with use_tenant(tenant.id):
        AccTaxFactory(tenant=tenant, type=AccTax.TYPE_SALE, rate=Decimal("20.000"))
        register = PosRegisterFactory(tenant=tenant)
        PosPaymentMethodFactory(tenant=tenant)
        open_session(tenant, register=register, cashier=user, opening_cash_amount=Decimal(10000))
    client = _client_for(tenant, user)

    response = client.get("/pos/sale/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 200
    assert b"posSale(" in response.content
    assert b"Ouvrir la session" not in response.content


def test_sale_screen_renders_the_last_order_confirmation_panel(web_pos) -> None:
    tenant, user = web_pos
    with use_tenant(tenant.id):
        AccTaxFactory(tenant=tenant, type=AccTax.TYPE_SALE, rate=Decimal("20.000"))
        register = PosRegisterFactory(tenant=tenant)
        cash = PosPaymentMethodFactory(tenant=tenant, type="cash")
        session_obj = open_session(
            tenant, register=register, cashier=user, opening_cash_amount=Decimal(0)
        )
        order = create_draft_order(
            tenant,
            session=session_obj,
            client_uuid=__import__("uuid").uuid4(),
            local_sequence=1,
            user=user,
        )
        add_line(
            order,
            line_type=PosOrderLine.TYPE_SERVICE,
            description="Service",
            qty=Decimal(1),
            unit_price=Decimal(1000),
        )
        order.refresh_from_db()
        add_payment(order, method=cash, amount=order.amount_total, user=user)
        validate_order(order, user=user, date=dt.date(2026, 1, 15))

    client = _client_for(tenant, user)
    response = client.get(f"/pos/sale/?order_id={order.id}", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 200
    assert order.number.encode() in response.content
