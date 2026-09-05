"""STK-6 (L13) — comptage a l'aveugle : la quantite attendue n'est exposee
ni par le service, ni par l'API, ni par le gabarit, ni par la feuille
d'inventaire tant que la session est ouverte.

**Ce que ces tests ferment.** Le gabarit masquait deja la quantite theorique
pendant le comptage, et son propre commentaire prevoyait le risque : « si
une future API serialise StkInventoryLine, elle doit reprendre la meme garde
par etat ». Elle ne l'a pas reprise. Deux fuites coexistaient donc avec un
ecran qui se croyait aveugle :

1. `POST /stocks/inventories/{id}/lines` renvoyait `qty_theoretical` en
   clair ;
2. la feuille d'inventaire STK-INV — dont le lien de telechargement est
   affiche JUSTE SOUS le tableau masque — restituait quantite attendue et
   ecart.

Un compteur muni d'un jeton d'API, ou d'un simple clic sur « Telecharger la
feuille d'inventaire », contournait le mode aveugle sans rien faire
d'anormal. C'est le biais que l'inventaire est cense eliminer : qui connait
le chiffre attendu le retrouve.

Le masquage rend `None` et jamais `0` : un stock theorique reellement nul
(premier comptage d'un emplacement jamais mouvemente) est un cas valide, et
le confondre avec « caché » serait une seconde erreur."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.test import Client

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import grant_role, use_tenant
from apps.stocks.models import StkInventory, StkLocation, StkMove
from apps.stocks.services.inventory import (
    add_inventory_line,
    create_inventory,
    record_count,
    start_inventory,
    validate_inventory,
    visible_inventory_line_rows,
)
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.reports import inventory_line_rows
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ngPassw0rd!23"
STOCKED_QTY = Decimal("42")


@pytest.fixture
def blind_setup():
    tenant = Tenant.objects.create(code="STK-BLIND", name="Stocks Blind Tenant")
    user = User.objects.create_user(email="magasinier-blind@example.com", password=PASSWORD)
    grant_role(user, "magasinier")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-B", name="Entrepot aveugle")
        location = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="B1",
            name="Rayon B1",
            type=StkLocation.TYPE_INTERNE,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS-B",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        variant_id = uuid.uuid4()
        validate_move(
            create_move(
                tenant=tenant,
                variant_id=variant_id,
                qty=STOCKED_QTY,
                uom="pc",
                location_from=supplier,
                location_to=location,
                date=dt.date(2026, 1, 1),
                move_type=StkMove.TYPE_RECEPTION,
                unit_cost_mga=Decimal("1000"),
            )
        )
        return tenant, warehouse, location, variant_id, user


def _blind_inventory(tenant, warehouse, location, variant_id, *, is_blind: bool = True):
    inventory = create_inventory(
        tenant=tenant,
        warehouse=warehouse,
        date=dt.date(2026, 2, 1),
        type=StkInventory.TYPE_TOURNANT,
        is_blind=is_blind,
    )
    add_inventory_line(inventory, variant_id=variant_id, location=location)
    return inventory


# ---------------------------------------------------------------------------
# Le service
# ---------------------------------------------------------------------------


def test_the_expected_quantity_is_hidden_while_the_session_is_open(blind_setup) -> None:
    tenant, warehouse, location, variant_id, _user = blind_setup
    with use_tenant(tenant.id):
        inventory = _blind_inventory(tenant, warehouse, location, variant_id)

        rows = visible_inventory_line_rows(inventory)
        assert rows[0]["qty_theoretical"] is None
        assert rows[0]["difference"] is None

        start_inventory(inventory)
        assert visible_inventory_line_rows(inventory)[0]["qty_theoretical"] is None


def test_the_expected_quantity_reappears_once_validated(blind_setup) -> None:
    """Apres validation, l'ecart doit etre lisible : c'est tout l'objet du
    document. Masquer definitivement rendrait l'inventaire inutilisable."""
    tenant, warehouse, location, variant_id, user = blind_setup
    with use_tenant(tenant.id):
        inventory = _blind_inventory(tenant, warehouse, location, variant_id)
        start_inventory(inventory)
        record_count(inventory.lines.first(), qty_counted=STOCKED_QTY, counted_by=user)
        validate_inventory(inventory, validated_by=user)

        rows = visible_inventory_line_rows(inventory)
        assert rows[0]["qty_theoretical"] == STOCKED_QTY
        assert rows[0]["difference"] == 0


def test_a_non_blind_inventory_shows_the_expected_quantity(blind_setup) -> None:
    """Le mode est un CHOIX : un inventaire ordinaire continue d'afficher la
    quantite attendue, comme avant L13."""
    tenant, warehouse, location, variant_id, _user = blind_setup
    with use_tenant(tenant.id):
        inventory = _blind_inventory(tenant, warehouse, location, variant_id, is_blind=False)
        assert visible_inventory_line_rows(inventory)[0]["qty_theoretical"] == STOCKED_QTY


def test_hidden_is_none_and_never_zero(blind_setup) -> None:
    """`None` et pas `0` : un stock theorique reellement nul est un cas
    valide (premier comptage d'un emplacement jamais mouvemente), et le
    confondre avec « cache » ferait croire a un ecart de 42."""
    tenant, warehouse, location, variant_id, _user = blind_setup
    with use_tenant(tenant.id):
        inventory = _blind_inventory(tenant, warehouse, location, variant_id)
        row = visible_inventory_line_rows(inventory)[0]
        assert row["qty_theoretical"] is None
        assert row["qty_theoretical"] != 0


# ---------------------------------------------------------------------------
# L'API — l'acces direct, celui qui fuyait
# ---------------------------------------------------------------------------


def _api(client: Client, tenant: Tenant, user: User) -> dict:
    token = client.post(
        "/api/v1/auth/login",
        {"email": user.email, "password": PASSWORD},
        content_type="application/json",
    ).json()["access"]
    return {"HTTP_AUTHORIZATION": f"Bearer {token}", "HTTP_X_TENANT_ID": str(tenant.id)}


def test_adding_a_line_over_the_api_never_returns_the_expected_quantity(blind_setup) -> None:
    """La fuite exacte : `POST .../lines` renvoyait `qty_theoretical` en
    clair alors que l'ecran la masquait."""
    tenant, warehouse, location, variant_id, user = blind_setup
    client = Client()
    headers = _api(client, tenant, user)

    created = client.post(
        "/api/v1/stocks/inventories",
        {
            "warehouse_id": str(warehouse.id),
            "date": "2026-02-01",
            "type": StkInventory.TYPE_TOURNANT,
            "is_blind": True,
        },
        content_type="application/json",
        **headers,
    )
    assert created.status_code == 200, created.content
    assert created.json()["is_blind"] is True
    inventory_id = created.json()["id"]

    line = client.post(
        f"/api/v1/stocks/inventories/{inventory_id}/lines",
        {"variant_id": str(variant_id), "location_id": str(location.id)},
        content_type="application/json",
        **headers,
    )
    assert line.status_code == 200, line.content
    assert line.json()["qty_theoretical"] is None
    assert str(STOCKED_QTY) not in line.content.decode()


def test_listing_lines_over_the_api_never_leaks_the_expected_quantity(blind_setup) -> None:
    tenant, warehouse, location, variant_id, user = blind_setup
    with use_tenant(tenant.id):
        inventory = _blind_inventory(tenant, warehouse, location, variant_id)
        start_inventory(inventory)

    client = Client()
    headers = _api(client, tenant, user)
    response = client.get(f"/api/v1/stocks/inventories/{inventory.id}/lines", **headers)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["is_blind"] is True
    assert body["results"][0]["qty_theoretical"] is None
    assert str(STOCKED_QTY) not in response.content.decode()


def test_the_inventory_sheet_never_leaks_the_expected_quantity(blind_setup) -> None:
    """La fuite la plus concrete : le lien « Telecharger la feuille
    d'inventaire » est affiche juste sous le tableau masque."""
    tenant, warehouse, location, variant_id, _user = blind_setup
    with use_tenant(tenant.id):
        inventory = _blind_inventory(tenant, warehouse, location, variant_id)
        start_inventory(inventory)

        rows = inventory_line_rows(inventory)
        assert rows[0]["qty_theoretical"] is None
        assert rows[0]["difference"] is None


def test_the_screen_never_renders_the_expected_quantity(blind_setup) -> None:
    """Absence du HTML RENDU, jamais un masquage cote client : une valeur
    presente dans la page et cachee en CSS reste lisible par qui regarde la
    source."""
    tenant, warehouse, location, variant_id, user = blind_setup
    with use_tenant(tenant.id):
        inventory = _blind_inventory(tenant, warehouse, location, variant_id)
        start_inventory(inventory)

    client = Client()
    assert client.post("/login/", {"email": user.email, "password": PASSWORD}).status_code == 302
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    response = client.get(f"/stocks/inventories/{inventory.id}/", HTTP_X_TENANT_ID=str(tenant.id))
    assert response.status_code == 200
    assert str(STOCKED_QTY) not in response.content.decode()
