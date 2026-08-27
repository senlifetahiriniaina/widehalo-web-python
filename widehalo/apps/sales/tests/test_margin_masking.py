"""RG-SAL-5 (§5.5, S7) : premiere mise en oeuvre reelle de
`apps.core.services.permissions.SENSITIVE_FIELDS`/`filter_fields_for_role`
— jamais utilise avant ce lot par aucun module.

Acceptance test §5.5.8 n°4 du CDC (verbatim) : « Un utilisateur sans
permission `sales.view_margin` ne voit pas le champ marge, ni en ecran ni
en API. »

**Interpretation assumee et documentee** (cf. plan, section RG-SAL-5) :
les permissions Django de ce projet sont auto-generees PAR MODELE
(`view_<model>`/`add_<model>`/`change_<model>`, cf.
`apps.core.services.rbac_policy` docstring, "granularite retenue : par
app plutot que par modele individuel") — il n'existe et ne peut exister
aucune permission `sales.view_margin` au sens Django litteral (ce serait
une permission de CHAMP, pas de modele/action). Ce test traite donc
« un utilisateur sans `sales.view_margin` » comme son equivalent pratique
dans ce systeme RBAC : un utilisateur dont AUCUN role n'appartient a
`SENSITIVE_FIELDS["sales.SalesOrderLine"]["margin_pct"]` — concretement,
un `commercial` pur (role qui a bien acces au module `sales` via
`ROLE_APP_PERMISSIONS`, donc peut voir la commande, mais pas la marge).
Ce n'est pas une permission fabriquee de toutes pieces pour coller au
mot du CDC : c'est la granularite N4 (champ) reellement disponible dans
ce projet, appliquee au cas du CDC."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.permissions import filter_fields_for_role
from apps.core.tests.utils import grant_role, use_tenant
from apps.sales.services.orders import add_order_line, create_order
from apps.sales.services.quotations import add_quotation_line, create_quotation

pytestmark = pytest.mark.django_db


def _access_token(client: Client, email: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/login",
        {"email": email, "password": password},
        content_type="application/json",
    )
    return response.json()["access"]


def _headers(token: str, tenant_id: str) -> dict:  # type: ignore[type-arg]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": tenant_id}


def test_filter_fields_for_role_masks_margin_for_plain_commercial() -> None:
    """Test unitaire direct du hook N4, sans passer par HTTP — sert de
    documentation executable de `SENSITIVE_FIELDS["sales.SalesOrderLine"]`."""
    data = {"id": "x", "margin_pct": Decimal("42.00"), "subtotal": Decimal("1000")}

    masked = filter_fields_for_role("sales.SalesOrderLine", {"commercial"}, data)
    assert "margin_pct" not in masked
    assert masked["subtotal"] == Decimal("1000")

    visible = filter_fields_for_role("sales.SalesOrderLine", {"resp_commercial"}, data)
    assert visible["margin_pct"] == Decimal("42.00")


def test_filter_fields_for_role_masks_margin_on_quotation_line_too() -> None:
    """`SalesQuotationLine.margin_pct` porte la meme sensibilite que
    `SalesOrderLine.margin_pct` (cf. commentaire dans
    `apps.core.services.permissions`) — verifie explicitement que les DEUX
    entrees du registre existent et se comportent identiquement."""
    data = {"margin_pct": Decimal("10.00")}
    assert "margin_pct" not in filter_fields_for_role(
        "sales.SalesQuotationLine", {"commercial"}, data
    )
    assert filter_fields_for_role("sales.SalesQuotationLine", {"admin"}, data)[
        "margin_pct"
    ] == Decimal("10.00")


@pytest.fixture
def margin_api_setup():
    tenant = Tenant.objects.create(code="MARGIN-API", name="Margin API Tenant")
    commercial = User.objects.create_user(
        email="commercial@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(commercial, "commercial")
    resp_commercial = User.objects.create_user(
        email="resp-commercial@example.com", password="Str0ngPassw0rd!23"
    )
    grant_role(resp_commercial, "resp_commercial")

    with use_tenant(tenant.id):
        order = create_order(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        add_order_line(
            order,
            description="Ligne avec marge",
            qty=Decimal(2),
            unit_price=Decimal(1000),
            is_custom=True,
        )
        line = order.lines.get()
        line.margin_pct = Decimal("35.50")
        line.cost_estimate_mga = Decimal("1300")
        line.save(update_fields=["margin_pct", "cost_estimate_mga"])

        quotation = create_quotation(tenant=tenant, partner_id=uuid.uuid4(), date=dt.date.today())
        add_quotation_line(
            quotation,
            description="Devis avec marge",
            qty=Decimal(1),
            unit_price=Decimal(500),
            is_custom=True,
        )
        quotation_line = quotation.lines.get()
        quotation_line.margin_pct = Decimal("20.00")
        quotation_line.save(update_fields=["margin_pct"])

    return tenant, commercial, resp_commercial, order, quotation


def test_acceptance_4_margin_hidden_from_plain_commercial_via_order_api(margin_api_setup) -> None:
    tenant, commercial, _resp, order, _quotation = margin_api_setup
    client = Client()
    token = _access_token(client, commercial.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get(f"/api/v1/sales/orders/{order.id}", **headers)
    assert response.status_code == 200
    line = response.json()["lines"][0]
    assert "margin_pct" not in line
    assert "cost_estimate_mga" not in line
    # Le reste de la ligne reste visible — seul le champ sensible est masque.
    assert line["subtotal"] == "2000.0000"


def test_acceptance_4_margin_visible_to_resp_commercial_via_order_api(margin_api_setup) -> None:
    tenant, _commercial, resp_commercial, order, _quotation = margin_api_setup
    client = Client()
    token = _access_token(client, resp_commercial.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get(f"/api/v1/sales/orders/{order.id}", **headers)
    assert response.status_code == 200
    line = response.json()["lines"][0]
    assert line["margin_pct"] == "35.50"
    assert line["cost_estimate_mga"] == "1300.0000"


def test_acceptance_4_margin_hidden_from_plain_commercial_via_quotation_api(
    margin_api_setup,
) -> None:
    tenant, commercial, _resp, _order, quotation = margin_api_setup
    client = Client()
    token = _access_token(client, commercial.email, "Str0ngPassw0rd!23")
    headers = _headers(token, str(tenant.id))

    response = client.get(f"/api/v1/sales/quotations/{quotation.id}", **headers)
    assert response.status_code == 200
    line = response.json()["lines"][0]
    assert "margin_pct" not in line


def test_acceptance_4_margin_hidden_from_plain_commercial_via_screen(margin_api_setup) -> None:
    """Volet ecran de l'acceptance test n°4 : `can_see_margin` (context de
    `apps.sales.views.order_detail`) doit etre `False` pour un
    `commercial`, et la colonne "Marge" absente du HTML rendu."""
    tenant, commercial, resp_commercial, order, _quotation = margin_api_setup
    client = Client()
    client.force_login(commercial)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/sales/orders/{order.id}/")
    assert response.status_code == 200
    assert b"Marge" not in response.content
    assert b"35,50" not in response.content

    client2 = Client()
    client2.force_login(resp_commercial)
    session2 = client2.session
    session2["tenant_id"] = str(tenant.id)
    session2.save()
    response2 = client2.get(f"/sales/orders/{order.id}/")
    assert response2.status_code == 200
    assert b"Marge" in response2.content
    assert b"35,50" in response2.content
