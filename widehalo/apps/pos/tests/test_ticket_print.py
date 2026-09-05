"""POS-1/POS-3 (L6) — le ticket imprimable, le rendu de monnaie et la
nature de mouvement « vente au comptoir ».

**Trois manques qui se documentaient eux-memes.**

1. `PosOrder.reprint_count` etait livre, incremente par
   `services.orders.mark_reprint`, et sa docstring annoncait que « l'ecran
   d'impression affiche DUPLICATA des que reprint_count > 0 ». Cet ecran
   n'existait nulle part : le compteur tracait les reimpressions d'un
   document qu'aucun code ne produisait.
2. `StkMove.TYPE_VENTE_COMPTOIR` existait depuis la Phase 3 SANS AUCUN
   PRODUCTEUR, sa propre declaration le disant : « le cablage reel
   d'`apps.pos` sur cette nouvelle valeur est un chantier distinct ». Toute
   sortie de caisse etait donc enregistree comme une `livraison`, et
   l'analyse des sorties par nature (cahier §9) restait muette sur la
   caisse.
3. L'ecran de vente exigeait un reglement egal au total au centime et
   n'affichait aucun rendu de monnaie — le caissier calculait de tete.
"""

from __future__ import annotations

import datetime as dt
import uuid
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
def ticket_ctx():
    tenant = Tenant.objects.create(code="POS-TICKET", name="POS Ticket Tenant")
    user = User.objects.create_user(email="pos-ticket@example.com", password="Str0ngPassw0rd!23")
    grant_role(user, "caissier")
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
            client_uuid=uuid.uuid4(),
            local_sequence=1,
            user=user,
        )
        add_line(
            order,
            line_type=PosOrderLine.TYPE_SERVICE,
            description="Coupe simple",
            qty=Decimal(1),
            unit_price=Decimal(7300),
        )
        order.refresh_from_db()
        add_payment(order, method=cash, amount=order.amount_total, user=user)
        validate_order(order, user=user, date=dt.date(2026, 1, 15))
    return tenant, user, order


def _client_for(tenant: Tenant, user: User) -> Client:
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


# ---------------------------------------------------------------------------
# Le ticket
# ---------------------------------------------------------------------------


def test_the_ticket_renders_with_its_lines_and_total(ticket_ctx) -> None:
    tenant, user, order = ticket_ctx
    client = _client_for(tenant, user)

    response = client.get(f"/pos/orders/{order.id}/ticket/", HTTP_X_TENANT_ID=str(tenant.id))

    assert response.status_code == 200
    body = response.content.decode()
    assert "Coupe simple" in body
    assert order.number in body
    assert "TOTAL TTC" in body


def test_a_first_print_is_never_marked_as_a_duplicate(ticket_ctx) -> None:
    tenant, user, order = ticket_ctx
    client = _client_for(tenant, user)

    response = client.get(f"/pos/orders/{order.id}/ticket/", HTTP_X_TENANT_ID=str(tenant.id))

    assert "DUPLICATA" not in response.content.decode()


def test_viewing_the_ticket_again_never_counts_a_reprint(ticket_ctx) -> None:
    """La trace de duplicata ne vaut que si elle compte des actes, pas des
    rechargements de page. Une vue GET qui incrementerait ferait grimper le
    compteur au moindre retour arriere du navigateur."""
    tenant, user, order = ticket_ctx
    client = _client_for(tenant, user)

    for _ in range(3):
        client.get(f"/pos/orders/{order.id}/ticket/", HTTP_X_TENANT_ID=str(tenant.id))

    order.refresh_from_db()
    assert order.reprint_count == 0


def test_declaring_a_reprint_marks_the_ticket_as_a_duplicate(ticket_ctx) -> None:
    tenant, user, order = ticket_ctx
    grant_role(user, "admin")  # `change_posorder` : declarer une reimpression ecrit.
    client = _client_for(tenant, user)

    response = client.post(
        f"/pos/orders/{order.id}/ticket/reprint/",
        {"width": "80"},
        HTTP_X_TENANT_ID=str(tenant.id),
    )
    assert response.status_code == 302

    order.refresh_from_db()
    assert order.reprint_count == 1

    reprinted = client.get(f"/pos/orders/{order.id}/ticket/", HTTP_X_TENANT_ID=str(tenant.id))
    assert "DUPLICATA" in reprinted.content.decode()


def test_the_ticket_supports_both_thermal_widths(ticket_ctx) -> None:
    """58 et 80 mm couvrent l'essentiel du parc thermique. Une largeur
    inventee retombe sur 80 plutot que de produire un ticket illisible sur
    du materiel qui n'existe pas."""
    tenant, user, order = ticket_ctx
    client = _client_for(tenant, user)
    url = f"/pos/orders/{order.id}/ticket/"

    assert "58mm" in client.get(f"{url}?width=58", HTTP_X_TENANT_ID=str(tenant.id)).content.decode()
    assert "80mm" in client.get(f"{url}?width=80", HTTP_X_TENANT_ID=str(tenant.id)).content.decode()
    assert (
        "80mm" in client.get(f"{url}?width=999", HTTP_X_TENANT_ID=str(tenant.id)).content.decode()
    )


def test_the_action_bar_is_hidden_when_printing(ticket_ctx) -> None:
    """Les boutons ne doivent jamais sortir sur le papier — regle CSS
    d'impression, pas un espoir."""
    tenant, user, order = ticket_ctx
    client = _client_for(tenant, user)

    body = client.get(f"/pos/orders/{order.id}/ticket/", HTTP_X_TENANT_ID=str(tenant.id))
    assert "@media print" in body.content.decode()
    assert ".actions { display: none; }" in body.content.decode()


def test_a_role_without_view_permission_is_refused(ticket_ctx) -> None:
    tenant, _user, order = ticket_ctx
    outsider = User.objects.create_user(email="hors-pos@example.com", password="Str0ngPassw0rd!23")
    grant_role(outsider, "rh")
    client = _client_for(tenant, outsider)

    response = client.get(f"/pos/orders/{order.id}/ticket/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Le rendu de monnaie
# ---------------------------------------------------------------------------


def test_the_sale_screen_offers_the_change_computation(ticket_ctx) -> None:
    """Le calcul vit cote client (l'ecran de caisse est l'une des deux
    exceptions assumees a la regle du rendu serveur, pour fonctionner hors
    ligne) : ce test verifie que le champ et le calcul sont bien servis."""
    tenant, user, _order = ticket_ctx
    client = _client_for(tenant, user)

    body = client.get("/pos/sale/", HTTP_X_TENANT_ID=str(tenant.id)).content.decode()

    assert "cash-tendered" in body
    assert "changeDue()" in body
    # Le rendu ne se calcule que sur les moyens de type especes : on ne rend
    # pas la monnaie d'un paiement par carte.
    assert 'm.type === "cash"' in body


def test_the_tendered_amount_is_never_submitted(ticket_ctx) -> None:
    """`cashTendered` est une aide au caissier, pas un reglement : les
    montants enregistres doivent toujours egaler le total au centime
    (`validate_order`). Le champ ne porte donc aucun `name`, il ne peut pas
    partir dans le formulaire."""
    tenant, user, _order = ticket_ctx
    client = _client_for(tenant, user)

    body = client.get("/pos/sale/", HTTP_X_TENANT_ID=str(tenant.id)).content.decode()

    assert 'name="cashTendered"' not in body
    assert 'name="cash_tendered"' not in body
    assert 'x-model.number="cashTendered"' in body


# ---------------------------------------------------------------------------
# La nature du mouvement de stock
# ---------------------------------------------------------------------------


def test_a_counter_sale_produces_a_counter_sale_move(ticket_ctx) -> None:
    """POS-3 : la sortie de caisse porte la nature `vente_comptoir`, pas
    `livraison`. Sans quoi l'analyse des sorties par nature confondrait la
    caisse avec l'expedition."""
    from apps.catalog.tests.factories import ProductVariantFactory
    from apps.stocks.models import StkLocation, StkMove
    from apps.stocks.services.moves import create_move, validate_move
    from apps.stocks.services.public import sell_from_stock
    from apps.stocks.services.warehouses import create_location, create_warehouse

    tenant, user, _order = ticket_ctx
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-POS", name="Entrepot caisse")
        shelf = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="P1",
            name="Rayon caisse",
            type=StkLocation.TYPE_INTERNE,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS-POS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="CLI-POS",
            name="Client",
            type=StkLocation.TYPE_CLIENT,
        )
        variant = ProductVariantFactory(tenant=tenant)
        validate_move(
            create_move(
                tenant=tenant,
                variant_id=variant.id,
                qty=Decimal(10),
                uom="pc",
                location_from=supplier,
                location_to=shelf,
                date=dt.date(2026, 1, 10),
                move_type=StkMove.TYPE_RECEPTION,
                unit_cost_mga=Decimal(500),
            )
        )

        picking_id = sell_from_stock(
            tenant,
            variant_id=variant.id,
            qty=Decimal(2),
            warehouse_id=warehouse.id,
            date=dt.date(2026, 1, 15),
            source_document="TICKET-TEST",
            operator=user,
        )
        assert picking_id is not None

        moves = StkMove.objects.filter(picking_id=picking_id)
        assert moves.exists()
        assert all(move.move_type == StkMove.TYPE_VENTE_COMPTOIR for move in moves), [
            move.move_type for move in moves
        ]
