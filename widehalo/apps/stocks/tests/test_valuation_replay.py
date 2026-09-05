"""STK-12 (L12) — la valeur de stock rejouee egale le solde du compte de
stock comptable, a l'ariary pres.

Critere, mot pour mot : « La valeur de stock a une date anterieure,
recalculee par rejeu des mouvements, est egale au solde du compte de stock
comptable a cette meme date, a l'ariary pres. »

**Ce que ces tests ferment.** Le cablage etait teste mouvement par
mouvement — chaque ecriture est equilibree en elle-meme. C'est une
propriete plus faible qu'il n'y parait : **une ecriture equilibree sur un
mauvais montant reste equilibree**. Personne ne verifiait le cumul. L'audit
le disait ainsi : « l'egalite est une consequence attendue de la
conception, non une propriete verifiee ».

**Pourquoi ces tests prouvent quelque chose.** Le rejeu
(`services.valuation_replay`) reconstruit les couches EN MEMOIRE depuis les
`StkMove`, sans jamais lire `StkValuationLayer` ni `StkQuant`. Il n'emprunte
donc pas le chemin qu'il verifie. Les tests existants
(`test_valuation.py`, `test_hypothesis_properties.py`) comparent le stock a
lui-meme — quant contre couches ; ceux-ci comparent le stock a la
comptabilite, qui est une source independante.

Trois tests portent sur le PERIMETRE plutot que sur un montant : ce sont
eux qui rendent l'egalite non triviale. Sans les exclusions
(interne<->interne, virtuel<->virtuel, `TYPE_AJUSTEMENT`), les deux cotes
divergeraient — les tests de divergence deliberee en font la demonstration.
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
from apps.core.tests.factories import UserFactory
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove, StkValuationLayer
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.negative_stock import grant_negative_stock_exception
from apps.stocks.services.valuation_replay import replay_stock_value, replay_unit_cost
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def replay_setup():
    tenant = Tenant.objects.create(code="STK-REPLAY", name="Stocks Replay Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-R", name="Entrepot rejeu")
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="R1",
            name="Rayon R1",
            type=StkLocation.TYPE_INTERNE,
        )
        internal_2 = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="R2",
            name="Rayon R2",
            type=StkLocation.TYPE_INTERNE,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS-R",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        client = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="CLI-R",
            name="Client",
            type=StkLocation.TYPE_CLIENT,
        )
        # Sans configuration comptable, `create_stock_movement_entry_from_source`
        # renvoie `None` en silence et aucune ecriture n'est postee : les deux
        # cotes vaudraient zero et l'egalite serait vraie sans rien prouver.
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_STOCK)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 12, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_STOCK)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)
        return tenant, internal, internal_2, supplier, client


def _move(tenant, *, variant_id, qty, frm, to, date, move_type, unit_cost=Decimal(0)):
    move = create_move(
        tenant=tenant,
        variant_id=variant_id,
        qty=qty,
        uom="pc",
        location_from=frm,
        location_to=to,
        date=date,
        move_type=move_type,
        unit_cost_mga=unit_cost,
    )
    return validate_move(move)


# ---------------------------------------------------------------------------
# L'egalite elle-meme
# ---------------------------------------------------------------------------


def test_replayed_value_equals_the_accounting_balance_after_a_single_reception(
    replay_setup,
) -> None:
    tenant, internal, _i2, supplier, _client = replay_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            frm=supplier,
            to=internal,
            date=dt.date(2026, 3, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost=Decimal(1500),
        )
        at = dt.date(2026, 3, 31)
        assert replay_stock_value(tenant, at_date=at) == get_stock_account_balance(
            tenant, at_date=at
        )
        assert replay_stock_value(tenant, at_date=at) == Decimal(15000)


def test_replayed_value_equals_the_accounting_balance_over_a_mixed_history(
    replay_setup,
) -> None:
    """Le cas qui compte : entrees a des couts differents, sorties au CUMP,
    et un transfert interne au milieu. C'est la sequence ou un rejeu naif
    se trompe."""
    tenant, internal, internal_2, supplier, client = replay_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            frm=supplier,
            to=internal,
            date=dt.date(2026, 3, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost=Decimal(1000),
        )
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(30),
            frm=supplier,
            to=internal,
            date=dt.date(2026, 3, 5),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost=Decimal(1400),
        )
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(7),
            frm=internal,
            to=internal_2,
            date=dt.date(2026, 3, 8),
            move_type=StkMove.TYPE_TRANSFERT_INTERNE,
        )
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(12),
            frm=internal,
            to=client,
            date=dt.date(2026, 3, 10),
            move_type=StkMove.TYPE_LIVRAISON,
        )

        at = dt.date(2026, 3, 31)
        replayed = replay_stock_value(tenant, at_date=at)
        booked = get_stock_account_balance(tenant, at_date=at)
        assert replayed == booked, f"rejeu={replayed} compta={booked}"
        assert replayed > 0


def test_the_equality_holds_at_every_intermediate_date(replay_setup) -> None:
    """« a une date anterieure » : l'egalite doit tenir a CHAQUE date, pas
    seulement a la fin. Une derive qui se compenserait en fin de periode
    passerait un test final et serait pourtant une erreur."""
    tenant, internal, _i2, supplier, client = replay_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(6),
            frm=supplier,
            to=internal,
            date=dt.date(2026, 4, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost=Decimal("1333.3333"),
        )
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(9),
            frm=supplier,
            to=internal,
            date=dt.date(2026, 4, 3),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost=Decimal("777.7777"),
        )
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(4),
            frm=internal,
            to=client,
            date=dt.date(2026, 4, 6),
            move_type=StkMove.TYPE_LIVRAISON,
        )
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(5),
            frm=internal,
            to=client,
            date=dt.date(2026, 4, 9),
            move_type=StkMove.TYPE_LIVRAISON,
        )

        for day in range(1, 12):
            at = dt.date(2026, 4, day)
            replayed = replay_stock_value(tenant, at_date=at)
            booked = get_stock_account_balance(tenant, at_date=at)
            assert replayed == booked, f"{at} : rejeu={replayed} compta={booked}"


# ---------------------------------------------------------------------------
# Le perimetre — les tests qui rendent l'egalite non triviale
# ---------------------------------------------------------------------------


def test_an_internal_transfer_moves_neither_side(replay_setup) -> None:
    """`validate_move` ne poste rien pour un transfert interne<->interne :
    la valeur ne quitte pas le perimetre. Le rejeu doit faire de meme,
    sinon il divergerait sur un mouvement parfaitement normal."""
    tenant, internal, internal_2, supplier, _client = replay_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            frm=supplier,
            to=internal,
            date=dt.date(2026, 5, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost=Decimal(800),
        )
        before = replay_stock_value(tenant, at_date=dt.date(2026, 5, 1))

        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(4),
            frm=internal,
            to=internal_2,
            date=dt.date(2026, 5, 2),
            move_type=StkMove.TYPE_TRANSFERT_INTERNE,
        )

        after = replay_stock_value(tenant, at_date=dt.date(2026, 5, 2))
        assert after == before
        assert after == get_stock_account_balance(tenant, at_date=dt.date(2026, 5, 2))


def test_a_scrap_movement_keeps_the_value_inside_the_perimeter(replay_setup) -> None:
    """RG-STK-7 : `TYPE_REBUT` compte comme interne au sens valorisation —
    un rebut ne fait pas sortir la valeur. Regle etablie du depot, et le
    rejeu doit l'appliquer sous peine de diverger sur du code correct."""
    tenant, internal, _i2, supplier, _client = replay_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        scrap = create_location(
            tenant=tenant,
            warehouse=internal.warehouse,
            code="REB-R",
            name="Rebut",
            type=StkLocation.TYPE_REBUT,
        )
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            frm=supplier,
            to=internal,
            date=dt.date(2026, 6, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost=Decimal(500),
        )
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(3),
            frm=internal,
            to=scrap,
            date=dt.date(2026, 6, 2),
            move_type=StkMove.TYPE_REBUT,
        )

        at = dt.date(2026, 6, 30)
        assert replay_stock_value(tenant, at_date=at) == Decimal(5000)
        assert replay_stock_value(tenant, at_date=at) == get_stock_account_balance(
            tenant, at_date=at
        )


def test_a_draft_move_counts_on_neither_side(replay_setup) -> None:
    """Un brouillon n'a aucune realite, ni en stock ni en comptabilite. Les
    deux cotes doivent appliquer la meme regle — sans quoi l'egalite
    dependrait du moment ou l'on regarde."""
    tenant, internal, _i2, supplier, _client = replay_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            frm=supplier,
            to=internal,
            date=dt.date(2026, 7, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost=Decimal(900),
        )
        create_move(  # jamais valide
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(50),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 7, 2),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal(900),
        )
        at = dt.date(2026, 7, 31)
        assert replay_stock_value(tenant, at_date=at) == Decimal(9000)
        assert replay_stock_value(tenant, at_date=at) == get_stock_account_balance(
            tenant, at_date=at
        )


# ---------------------------------------------------------------------------
# Voir l'egalite echouer — sans quoi elle ne prouve rien
# ---------------------------------------------------------------------------


def test_a_movement_validated_before_the_accounting_setup_breaks_the_equality() -> None:
    """LE test qui donne leur valeur a tous les autres : voir l'egalite
    ECHOUER.

    Le scenario n'est pas invente. `create_stock_movement_entry_from_source`
    retourne `None` sans exception quand le journal, la periode ou un compte
    par defaut manquent — discipline assumee « un gap de configuration ne
    bloque jamais un mouvement de stock ». Un tenant qui recoit de la
    marchandise avant d'avoir configure sa comptabilite a donc du stock
    valorise et AUCUNE ecriture. Les deux cotes doivent diverger, et
    l'ecart doit valoir exactement la valeur non comptabilisee.

    On ne fausse PAS un `StkMove` valide pour produire cette divergence : le
    declencheur `stk_move_reject_mutation_if_done` l'interdit en base, et
    c'est tant mieux. La premiere version de ce test essayait, et s'est fait
    refuser par le depot — l'immuabilite fonctionne."""
    tenant = Tenant.objects.create(code="STK-REPLAY-GAP", name="Stocks Replay Gap Tenant")
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-G", name="Entrepot gap")
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="G1",
            name="Rayon G1",
            type=StkLocation.TYPE_INTERNE,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="GFRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )

        # Aucune configuration comptable a cet instant : le mouvement passe,
        # l'ecriture non.
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            frm=supplier,
            to=internal,
            date=dt.date(2026, 8, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost=Decimal(1000),
        )

        at = dt.date(2026, 8, 31)
        replayed = replay_stock_value(tenant, at_date=at)
        booked = get_stock_account_balance(tenant, at_date=at)
        assert replayed == Decimal("10000.0000")
        assert booked == Decimal(0)
        assert replayed != booked


def test_a_falsified_valuation_layer_does_not_move_the_replay(replay_setup) -> None:
    """Le rejeu doit ignorer `StkValuationLayer`, sans quoi il relirait ce
    que le moteur a ecrit au lieu de le recalculer — et l'egalite ne
    prouverait rien.

    On fausse donc une couche, pas un mouvement : la couche est un etat
    derive, rien en base ne l'interdit. Le rejeu ne doit pas broncher, et
    l'egalite avec la comptabilite doit tenir malgre la couche fausse."""
    tenant, internal, _i2, supplier, _client = replay_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            frm=supplier,
            to=internal,
            date=dt.date(2026, 8, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost=Decimal(1000),
        )
        at = dt.date(2026, 8, 31)
        before = replay_stock_value(tenant, at_date=at)
        assert before == get_stock_account_balance(tenant, at_date=at)

        StkValuationLayer.objects.filter(tenant=tenant, variant_id=variant_id).update(
            remaining_value_mga=Decimal("999999"),
            unit_cost_mga=Decimal("99999"),
        )

        assert replay_stock_value(tenant, at_date=at) == before
        assert replay_stock_value(tenant, at_date=at) == get_stock_account_balance(
            tenant, at_date=at
        )


# ---------------------------------------------------------------------------
# Le CUMP historise (prealable de PRD-9)
# ---------------------------------------------------------------------------


def test_the_replayed_unit_cost_is_the_one_of_its_date_not_of_today(replay_setup) -> None:
    """`get_variant_unit_cost` ne sait donner que le CUMP COURANT. PRD-9
    exige celui « a la date d'effet » de chaque consommation — c'est ce que
    ce rejeu fournit, et c'est ce qui les distingue."""
    tenant, internal, _i2, supplier, _client = replay_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            frm=supplier,
            to=internal,
            date=dt.date(2026, 9, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost=Decimal(1000),
        )
        assert replay_unit_cost(tenant, variant_id=variant_id, at_date=dt.date(2026, 9, 2)) == (
            Decimal("1000.0000")
        )

        # Une seconde entree, bien plus chere, deplace le CUMP courant.
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            frm=supplier,
            to=internal,
            date=dt.date(2026, 9, 10),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost=Decimal(3000),
        )

        # Le CUMP du 2 septembre n'a pas bouge : c'est tout l'objet.
        assert replay_unit_cost(tenant, variant_id=variant_id, at_date=dt.date(2026, 9, 2)) == (
            Decimal("1000.0000")
        )
        assert replay_unit_cost(tenant, variant_id=variant_id, at_date=dt.date(2026, 9, 11)) == (
            Decimal("2000.0000")
        )


def test_the_replayed_unit_cost_is_none_without_stock(replay_setup) -> None:
    """`None` et jamais zero : un zero serait un chiffre faux la ou il n'y
    a pas de cout a produire."""
    tenant, _internal, _i2, _supplier, _client = replay_setup
    with use_tenant(tenant.id):
        assert (
            replay_unit_cost(tenant, variant_id=uuid.uuid4(), at_date=dt.date(2026, 9, 1)) is None
        )


def test_a_negative_stock_exit_breaks_the_equality_and_the_accounting_is_the_wrong_side(
    replay_setup,
) -> None:
    """Reserve documentee du module de rejeu, rendue opposable.

    Avec une exception RG-STK-10, une sortie peut porter sur plus que le
    stock detenu. `_consume_average_cost` valorise le reliquat au cout
    fourni par l'appelant, et le compte de stock est credite de ce montant
    EN PLUS : il passe sous zero. Le rejeu, lui, ne peut pas vider plus que
    ce que les couches contiennent et s'arrete a zero.

    L'egalite STK-12 ne tient donc pas dans ce cas — et c'est la
    comptabilite qui a tort : un compte de stock negatif est une anomalie
    en soi. Ce test fige l'ecart (exactement le reliquat non couvert) pour
    que la reserve cesse d'etre de la prose."""
    tenant, internal, _i2, supplier, client = replay_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            frm=supplier,
            to=internal,
            date=dt.date(2026, 10, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost=Decimal(1000),
        )
        grant_negative_stock_exception(
            tenant=tenant,
            variant_id=variant_id,
            authorized_by=UserFactory(),
            reason="Reserve STK-12 — sortie au-dela du stock detenu",
        )
        _move(
            tenant,
            variant_id=variant_id,
            qty=Decimal(15),
            frm=internal,
            to=client,
            date=dt.date(2026, 10, 5),
            move_type=StkMove.TYPE_LIVRAISON,
            unit_cost=Decimal(500),
        )

        at = dt.date(2026, 10, 31)
        replayed = replay_stock_value(tenant, at_date=at)
        booked = get_stock_account_balance(tenant, at_date=at)

        # Le rejeu s'arrete a zero : les couches ne contenaient que 10.
        assert replayed == Decimal(0)
        # La comptabilite a credite 10 000 (les couches) + 5 x 500 (le
        # reliquat au cout de l'appelant) contre une entree de 10 000.
        assert booked == Decimal("-2500.0000")
        assert replayed != booked
