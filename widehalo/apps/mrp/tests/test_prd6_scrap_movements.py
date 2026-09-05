"""PRD-6 (L12-4) — le rebut atteint enfin le stock, et le taux de
conformite au premier passage est recalculable depuis les mouvements.

Critere, mot pour mot : « Le taux de conformite au premier passage est
calcule depuis les declarations reelles et non saisi ; il est
**recalculable a l'identique depuis les mouvements**. »

**La premiere moitie etait vraie, la seconde etait infaisable.**
`services.quality.first_pass_yield` calcule bien depuis
`MrpWorkOrder.qty_done`/`qty_rejected`, jamais saisi. Mais AUCUN
`StkMove.TYPE_REBUT` n'existait dans le depot :
`services.interventions.declare_scrap` disait lui-meme que le mouvement
« sera branche […] une fois ces modules disponibles », alors que `mrp`
consommait deja `stocks.services.public` depuis A2. Le rebut n'atteignait
jamais le stock — il n'y avait donc rien a recalculer.

**Le piege du comptage par poste.** Le FPY somme sur TOUS les ordres de
travail : sur une gamme a trois postes, la meme piece est comptee trois
fois. Un recalcul naif qui prendrait la quantite reellement entree en
stock (`production_in`, dix pieces) comme quantite bonne donnerait un taux
franchement faux. `test_a_naive_recomputation_from_the_production_entry_
is_wrong` le chiffre plutot que de le decrire.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccJournal
from apps.accounting.services.public import get_stock_account_balance
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.mrp.models import MrpWorkcenter, MrpWorkshop
from apps.mrp.services.bom import activate_bom, add_bom_line, create_bom
from apps.mrp.services.interventions import declare_scrap
from apps.mrp.services.orders import (
    create_order,
    create_work_order,
    done_work_order,
    scrap_declaration_source_document,
    scrap_source_document,
)
from apps.mrp.services.quality import (
    first_pass_yield,
    first_pass_yield_from_moves,
    scrapped_qty_by_workstation,
)
from apps.stocks.models import StkLocation, StkMove
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.public import list_scrap_quantities_by_source
from apps.stocks.services.valuation_replay import replay_stock_value
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db

# Gamme a TROIS postes : sans plusieurs postes, la subtilite du comptage
# multiple ne serait jamais exercee, et c'est precisement la que le
# recalcul naif se trompe.
QTY_DONE_PER_STATION = Decimal(10)
REJECTED_PER_STATION = (Decimal(2), Decimal(1), Decimal(3))


@pytest.fixture
def scrap_setup():
    tenant = Tenant.objects.create(code="MRP-PRD6", name="MRP Scrap Tenant")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="prd6@example.com", password="Str0ngPassw0rd!23")
        warehouse = create_warehouse(tenant=tenant, code="WH-SCR", name="Entrepot rebut")
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="SCR1",
            name="Rayon SCR1",
            type=StkLocation.TYPE_INTERNE,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="SCRF",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        workshop = MrpWorkshop.objects.create(
            tenant=tenant, code="ATL-SCR", name="Atelier", warehouse_id=warehouse.id
        )
        workcenter = MrpWorkcenter.objects.create(
            tenant=tenant,
            workshop=workshop,
            code="WC-SCR",
            name="Poste",
            type=MrpWorkcenter.TYPE_SEWING,
        )
        variant_id = uuid.uuid4()
        bom = create_bom(tenant=tenant, code="BOM-SCR", product_template_id=uuid.uuid4())
        add_bom_line(
            bom,
            component_template_id=uuid.uuid4(),
            component_variant_id=uuid.uuid4(),
            qty=Decimal(1),
        )
        activate_bom(bom)
        order = create_order(
            tenant=tenant,
            bom=bom,
            workshop=workshop,
            qty=Decimal(10),
            variant_id=variant_id,
        )
        return tenant, user, order, workcenter, variant_id, internal, supplier


def _three_stations(order, workcenter):
    """Trois postes de la meme gamme, termines avec leur propre rebut."""
    for index, rejected in enumerate(REJECTED_PER_STATION, start=1):
        work_order = create_work_order(
            order, workcenter=workcenter, qty_planned=QTY_DONE_PER_STATION, sequence=index
        )
        done_work_order(work_order, qty_done=QTY_DONE_PER_STATION, qty_rejected=rejected)


# ---------------------------------------------------------------------------
# Le rebut existe enfin
# ---------------------------------------------------------------------------


def test_a_work_order_reject_produces_a_scrap_movement(scrap_setup) -> None:
    """Ce que le depot ne faisait pas du tout avant ce lot."""
    tenant, _user, order, workcenter, variant_id, _internal, _supplier = scrap_setup
    with use_tenant(tenant.id):
        work_order = create_work_order(
            order, workcenter=workcenter, qty_planned=Decimal(10), sequence=1
        )
        done_work_order(work_order, qty_done=Decimal(10), qty_rejected=Decimal(2))

        move = StkMove.objects.get(tenant=tenant, move_type=StkMove.TYPE_REBUT)
        assert move.state == StkMove.STATE_DONE
        assert move.qty == Decimal(2)
        assert move.variant_id == variant_id
        assert move.source_document == scrap_source_document(order, work_order)
        assert move.location_to.type == StkLocation.TYPE_REBUT
        assert move.location_from.type == StkLocation.TYPE_PRODUCTION


def test_a_reject_of_zero_produces_no_movement(scrap_setup) -> None:
    """Un mouvement a quantite nulle n'a aucune realite physique — et
    `create_move` le refuse (RG-STK-1). La garde vit donc en amont."""
    tenant, _user, order, workcenter, _variant_id, _internal, _supplier = scrap_setup
    with use_tenant(tenant.id):
        work_order = create_work_order(
            order, workcenter=workcenter, qty_planned=Decimal(10), sequence=1
        )
        done_work_order(work_order, qty_done=Decimal(10), qty_rejected=Decimal(0))

        assert not StkMove.objects.filter(tenant=tenant, move_type=StkMove.TYPE_REBUT).exists()


def test_a_declared_scrap_produces_its_own_movement_under_a_distinct_document(
    scrap_setup,
) -> None:
    """La promesse tenue de `declare_scrap`, et la separation des deux
    natures de rebut : documents distincts, jamais melanges."""
    tenant, user, order, workcenter, _variant_id, _internal, _supplier = scrap_setup
    with use_tenant(tenant.id):
        work_order = create_work_order(
            order, workcenter=workcenter, qty_planned=Decimal(10), sequence=1
        )
        done_work_order(work_order, qty_done=Decimal(10), qty_rejected=Decimal(2))
        declare_scrap(order, declared_by=user, qty=Decimal(5), reason="Chute de tissu")

        documents = set(
            StkMove.objects.filter(tenant=tenant, move_type=StkMove.TYPE_REBUT).values_list(
                "source_document", flat=True
            )
        )
        assert documents == {
            scrap_source_document(order, work_order),
            scrap_declaration_source_document(order),
        }


# ---------------------------------------------------------------------------
# Le recalcul (le critere lui-meme)
# ---------------------------------------------------------------------------


def test_the_fpy_recomputed_from_moves_equals_the_declared_one(scrap_setup) -> None:
    """Le critere, sur une gamme a TROIS postes."""
    tenant, _user, order, workcenter, _variant_id, _internal, _supplier = scrap_setup
    with use_tenant(tenant.id):
        _three_stations(order, workcenter)

        declared = first_pass_yield(order)
        recomputed = first_pass_yield_from_moves(order)

        assert recomputed == declared
        # 30 bonnes sur 36 passages : ni 100 % (l'egalite serait vraie sur
        # du vide) ni un chiffre rond ou une erreur passerait inapercue.
        assert declared == (Decimal(30) / Decimal(36)) * Decimal(100)


def test_each_station_keeps_its_own_scrapped_quantity(scrap_setup) -> None:
    """Sans attribution par poste, le recalcul ne pourrait ni exclure un
    rebut declare ni detecter qu'un poste n'a rien trace."""
    tenant, _user, order, workcenter, _variant_id, _internal, _supplier = scrap_setup
    with use_tenant(tenant.id):
        _three_stations(order, workcenter)

        assert scrapped_qty_by_workstation(order) == {
            1: Decimal(2),
            2: Decimal(1),
            3: Decimal(3),
        }


def test_a_declared_scrap_never_inflates_the_recomputed_fpy(scrap_setup) -> None:
    """Le FPY lit `MrpWorkOrder.qty_rejected`, jamais `MrpScrap`. Si les
    deux natures de rebut partageaient un document, le rebut declare
    entrerait dans le denominateur et le taux recalcule serait faux —
    c'est la raison d'etre des `source_document` distincts."""
    tenant, user, order, workcenter, _variant_id, _internal, _supplier = scrap_setup
    with use_tenant(tenant.id):
        _three_stations(order, workcenter)
        before = first_pass_yield_from_moves(order)

        declare_scrap(order, declared_by=user, qty=Decimal(5), reason="Chute de tissu")

        assert first_pass_yield_from_moves(order) == before
        assert first_pass_yield_from_moves(order) == first_pass_yield(order)

        # Et la demonstration de ce qu'un melange couterait : en sommant
        # TOUS les mouvements de rebut de l'ordre, le denominateur passe de
        # 36 a 41 et le taux devient faux.
        every_document = list(
            StkMove.objects.filter(tenant=tenant, move_type=StkMove.TYPE_REBUT).values_list(
                "source_document", flat=True
            )
        )
        mixed_total = sum(
            list_scrap_quantities_by_source(tenant, source_documents=every_document).values(),
            Decimal(0),
        )
        assert mixed_total == Decimal(11)
        naive = (Decimal(30) / (Decimal(30) + mixed_total)) * Decimal(100)
        assert naive != before


def test_a_naive_recomputation_from_the_production_entry_is_wrong(scrap_setup) -> None:
    """Le piege que la docstring de `first_pass_yield_from_moves` annonce.

    La quantite BONNE n'a aucune contrepartie par poste : le seul mouvement
    d'entree porte sur l'ordre entier (dix pieces), alors que le FPY somme
    `qty_done` sur les trois postes (trente). Un recalcul qui prendrait
    l'entree de production pour quantite bonne donnerait 62,5 % la ou le
    taux reel est 83,33 %. C'est pourquoi cette moitie est lue sur les
    ordres de travail, et pourquoi la fonction le dit."""
    tenant, _user, order, workcenter, variant_id, _internal, supplier = scrap_setup
    with use_tenant(tenant.id):
        _three_stations(order, workcenter)
        # L'entree de production reelle de l'ordre : dix pieces bonnes.
        internal = StkLocation.objects.get(tenant=tenant, code="SCR1")
        validate_move(
            create_move(
                tenant=tenant,
                variant_id=variant_id,
                qty=Decimal(10),
                uom="pc",
                location_from=supplier,
                location_to=internal,
                date=dt.date(2026, 5, 1),
                move_type=StkMove.TYPE_PRODUCTION_IN,
                source_document=order.reference,
            )
        )

        entered = StkMove.objects.get(tenant=tenant, move_type=StkMove.TYPE_PRODUCTION_IN).qty
        scrapped_total = sum(REJECTED_PER_STATION, Decimal(0))
        naive = (entered / (entered + scrapped_total)) * Decimal(100)

        assert entered == Decimal(10)
        assert naive == Decimal("62.5")
        assert first_pass_yield_from_moves(order) != naive
        assert first_pass_yield_from_moves(order) == first_pass_yield(order)


# ---------------------------------------------------------------------------
# Le rebut ne deplace aucun montant (verifie, pas affirme)
# ---------------------------------------------------------------------------


def test_scrapping_moves_no_amount_at_all(scrap_setup) -> None:
    """RG-STK-7 et la garde `value_delta != 0` de `validate_move` : le
    rebut rend la quantite tracable sans changer la valeur de stock ni le
    solde du compte de stock. Verifie contre le rejeu de L12-1 (STK-12),
    qui reconstruit la valeur depuis les mouvements — donc y compris les
    nouveaux."""
    tenant, user, order, workcenter, _variant_id, internal, supplier = scrap_setup
    with use_tenant(tenant.id):
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_STOCK)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 12, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_STOCK)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)
        validate_move(
            create_move(
                tenant=tenant,
                variant_id=uuid.uuid4(),
                qty=Decimal(20),
                uom="pc",
                location_from=supplier,
                location_to=internal,
                date=dt.date(2026, 5, 1),
                move_type=StkMove.TYPE_RECEPTION,
                unit_cost_mga=Decimal(1000),
            )
        )
        at = dt.date(2026, 12, 31)
        value_before = replay_stock_value(tenant, at_date=at)
        balance_before = get_stock_account_balance(tenant, at_date=at)
        assert value_before == Decimal("20000.0000")
        assert balance_before == value_before

        _three_stations(order, workcenter)
        declare_scrap(order, declared_by=user, qty=Decimal(5), reason="Chute de tissu")

        assert StkMove.objects.filter(tenant=tenant, move_type=StkMove.TYPE_REBUT).count() == 4
        assert replay_stock_value(tenant, at_date=at) == value_before
        assert get_stock_account_balance(tenant, at_date=at) == balance_before


# ---------------------------------------------------------------------------
# Le repli, declare
# ---------------------------------------------------------------------------


def test_a_workshop_without_a_warehouse_logs_instead_of_failing_silently(
    scrap_setup, caplog
) -> None:
    """Un gap de configuration ne doit jamais faire echouer une
    declaration de production — mais il ne doit pas disparaitre en
    silence, sous peine de reproduire le defaut que ce lot corrige : une
    quantite declaree que rien ne trace."""
    tenant, _user, order, workcenter, _variant_id, _internal, _supplier = scrap_setup
    with use_tenant(tenant.id):
        order.workshop.warehouse_id = None
        order.workshop.save(update_fields=["warehouse_id"])

        work_order = create_work_order(
            order, workcenter=workcenter, qty_planned=Decimal(10), sequence=1
        )
        with caplog.at_level("WARNING"):
            done_work_order(work_order, qty_done=Decimal(10), qty_rejected=Decimal(2))

        work_order.refresh_from_db()
        assert work_order.qty_rejected == Decimal(2)
        assert not StkMove.objects.filter(tenant=tenant, move_type=StkMove.TYPE_REBUT).exists()
        assert any("Rebut non trace en stock" in record.message for record in caplog.records)
