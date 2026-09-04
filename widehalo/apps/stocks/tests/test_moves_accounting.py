"""STK-12 (cahier Phase 3 §5.8, sprint A3) : `services.moves.validate_move`
poste desormais une ecriture comptable equilibree sur tout mouvement
ORDINAIRE qui entre ou sort reellement du perimetre de valorisation trace
(reception, livraison, production, retour, rebut, casse, vente au
comptoir, sous-produit) — via `accounting.services.public.
create_stock_movement_entry_from_source` (renommee/generalisee depuis
`create_stock_adjustment_entry_from_source`, ST5). `TYPE_TRANSFERT_INTERNE`
(aucun changement de valeur agregee) et `TYPE_AJUSTEMENT` (deja couvert
par son propre appel dedie depuis `services.inventory.validate_inventory`,
cf. `test_inventory.py`) n'en beneficient PAS — testes explicitement
ci-dessous pour prouver l'absence d'ecriture, pas seulement sa presence."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccJournal, AccMove
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant
from apps.stocks.models import StkLocation, StkMove
from apps.stocks.services.moves import create_move, validate_move
from apps.stocks.services.warehouses import create_location, create_warehouse

pytestmark = pytest.mark.django_db


@pytest.fixture
def moves_accounting_setup():
    tenant = Tenant.objects.create(code="STK-MVACC-T", name="Stocks Moves Accounting Tenant")
    with use_tenant(tenant.id):
        warehouse = create_warehouse(tenant=tenant, code="WH-01", name="Entrepot principal")
        internal = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A1",
            name="Rayon A1",
            type=StkLocation.TYPE_INTERNE,
        )
        internal_2 = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="A2",
            name="Rayon A2",
            type=StkLocation.TYPE_INTERNE,
        )
        supplier = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="FRS",
            name="Fournisseur",
            type=StkLocation.TYPE_FOURNISSEUR,
        )
        client = create_location(
            tenant=tenant,
            warehouse=warehouse,
            code="CLI",
            name="Client",
            type=StkLocation.TYPE_CLIENT,
        )
        return tenant, internal, internal_2, supplier, client


def _accounting_config(tenant):
    AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_STOCK)
    AccPeriodFactory(tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 12, 31))
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_STOCK)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)


def test_validate_move_posts_balanced_entry_on_reception(moves_accounting_setup) -> None:
    tenant, internal, _i2, supplier, _client = moves_accounting_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _accounting_config(tenant)

        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 3, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1000"),
        )
        validate_move(move)

        acc_move = AccMove.objects.get(tenant=tenant)
        assert acc_move.move_type == AccMove.TYPE_ENTRY
        assert acc_move.state == AccMove.STATE_POSTED
        assert acc_move.total_debit == Decimal("10000.0000")
        assert acc_move.total_credit == Decimal("10000.0000")
        debit_line = acc_move.lines.get(debit__gt=0)
        credit_line = acc_move.lines.get(credit__gt=0)
        assert debit_line.account.type == AccAccount.TYPE_STOCK
        assert credit_line.account.type == AccAccount.TYPE_EXPENSE


def test_validate_move_posts_balanced_entry_on_livraison(moves_accounting_setup) -> None:
    tenant, internal, _i2, supplier, client = moves_accounting_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _accounting_config(tenant)

        reception = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 3, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1000"),
        )
        validate_move(reception)

        livraison = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(4),
            uom="pc",
            location_from=internal,
            location_to=client,
            date=dt.date(2026, 3, 2),
            move_type=StkMove.TYPE_LIVRAISON,
        )
        validate_move(livraison)

        livraison_entry = AccMove.objects.get(tenant=tenant, narration=livraison.reference)
        assert livraison_entry.total_debit == Decimal("4000.0000")
        assert livraison_entry.total_credit == Decimal("4000.0000")
        debit_line = livraison_entry.lines.get(debit__gt=0)
        credit_line = livraison_entry.lines.get(credit__gt=0)
        # Corrige par le premier passage CI avec une vraie base (l'hypothese
        # initiale, non verifiee faute de DB, etait inversee). La resolution
        # de compte par defaut de `create_stock_movement_entry_from_source`
        # est PAR SIGNE, pas par sens du mouvement (cf. sa docstring) :
        # positif/debit -> TYPE_STOCK, negatif/credit -> TYPE_EXPENSE,
        # SYSTEMATIQUEMENT — meme convention deja en place cote ST5
        # (`services.inventory.validate_inventory`, ligne "Sortie ajustement
        # inventaire" deja negative) que la sortie mirroir ici respecte a
        # l'identique (`moves.py` : "Sortie stock" = -value_delta,
        # "Contrepartie" = +value_delta).
        assert debit_line.account.type == AccAccount.TYPE_STOCK
        assert credit_line.account.type == AccAccount.TYPE_EXPENSE
        assert AccMove.objects.filter(tenant=tenant).count() == 2


def test_validate_move_transfert_interne_posts_no_accounting_entry(moves_accounting_setup) -> None:
    """Transfert interne->interne : la valeur reste integralement dans le
    perimetre trace, le solde du compte de stock agrege ne change pas —
    aucune ecriture ne doit etre postee (a la difference de reception/
    livraison ci-dessus)."""
    tenant, internal, internal_2, supplier, _client = moves_accounting_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _accounting_config(tenant)

        reception = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 3, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1000"),
        )
        validate_move(reception)
        count_before_transfert = AccMove.objects.filter(tenant=tenant).count()

        transfert = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(3),
            uom="pc",
            location_from=internal,
            location_to=internal_2,
            date=dt.date(2026, 3, 2),
            move_type=StkMove.TYPE_TRANSFERT_INTERNE,
        )
        validate_move(transfert)

        assert AccMove.objects.filter(tenant=tenant).count() == count_before_transfert


def test_validate_move_does_not_double_post_for_ajustement(moves_accounting_setup) -> None:
    """`TYPE_AJUSTEMENT` beneficie deja de son propre appel comptable dedie
    depuis `services.inventory.validate_inventory` (labels "Ecart
    d'inventaire" specifiques, cf. `test_inventory.py`) — `validate_move`
    lui-meme ne doit JAMAIS poster d'ecriture pour ce move_type, meme
    appele directement (pas seulement via le flux inventaire), pour ne
    jamais doubler l'ecriture d'un meme mouvement."""
    tenant, internal, _i2, supplier, _client = moves_accounting_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        _accounting_config(tenant)

        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(5),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 3, 1),
            move_type=StkMove.TYPE_AJUSTEMENT,
            unit_cost_mga=Decimal("200"),
        )
        validate_move(move)

        assert AccMove.objects.filter(tenant=tenant).count() == 0


def test_validate_move_never_blocked_by_missing_accounting_config(moves_accounting_setup) -> None:
    """Meme discipline "gap de configuration a la charge du tenant, jamais
    un blocage du mouvement de stock" que `services.inventory.
    validate_inventory` : sans aucune configuration comptable, la
    reception se valide normalement, sans exception, aucune `AccMove`
    n'est creee."""
    tenant, internal, _i2, supplier, _client = moves_accounting_setup
    variant_id = uuid.uuid4()
    with use_tenant(tenant.id):
        move = create_move(
            tenant=tenant,
            variant_id=variant_id,
            qty=Decimal(10),
            uom="pc",
            location_from=supplier,
            location_to=internal,
            date=dt.date(2026, 3, 1),
            move_type=StkMove.TYPE_RECEPTION,
            unit_cost_mga=Decimal("1000"),
        )
        validated = validate_move(move)

        assert validated.state == StkMove.STATE_DONE
        assert AccMove.objects.filter(tenant=tenant).count() == 0
