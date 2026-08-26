from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection, transaction

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccMove, AccPeriod
from apps.accounting.services.moves import add_line, create_draft_move, post_move, reverse_move
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


@pytest.fixture
def ledger():
    tenant = Tenant.objects.create(code="ACC-MOVE", name="Accounting Moves Tenant")
    with use_tenant(tenant.id):
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2026",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        period = AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fiscal_year,
            code="2026-01",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        journal = AccJournal.objects.create(
            tenant=tenant,
            code="OD",
            name="Operations diverses",
            type=AccJournal.TYPE_MISC,
            sequence_prefix="OD",
        )
        receivable = AccAccount.objects.create(
            tenant=tenant,
            code="411",
            name="Clients",
            account_class=4,
            type=AccAccount.TYPE_RECEIVABLE,
        )
        income = AccAccount.objects.create(
            tenant=tenant, code="701", name="Ventes", account_class=7, type=AccAccount.TYPE_INCOME
        )
        return tenant, fiscal_year, period, journal, receivable, income


def _balanced_move(ledger, amount=Decimal("1000")):
    tenant, _fy, period, journal, receivable, income = ledger
    move = create_draft_move(
        tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 15)
    )
    add_line(move, account=receivable, label="Vente", debit=amount)
    add_line(move, account=income, label="Vente", credit=amount)
    return move


def test_balanced_move_can_be_posted_and_gets_a_reference(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        move = _balanced_move(ledger)
        assert move.reference == ""

        posted = post_move(move)
        assert posted.state == AccMove.STATE_POSTED
        assert posted.reference.startswith("OD-2026-")
        assert posted.total_debit == posted.total_credit == Decimal("1000")


def test_unbalanced_move_is_rejected_at_service_level(ledger) -> None:
    tenant, _fy, period, journal, receivable, income = ledger
    with use_tenant(tenant.id):
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 1, 15)
        )
        add_line(move, account=receivable, debit=Decimal("1000"))
        add_line(move, account=income, credit=Decimal("900"))

        with pytest.raises(ValidationError):
            post_move(move)


def test_unbalanced_move_is_rejected_at_database_level(ledger) -> None:
    """Contourne le service et tente directement le SQL — la contrainte
    CHECK doit refuser, meme pour le proprietaire de la table (RG-ACC-1)."""
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        move = _balanced_move(ledger)
        move.total_credit = Decimal("1")  # desequilibre volontaire avant le UPDATE brut
        move.save(update_fields=["total_credit"])

        # La verification SQL brute doit se faire dans son propre savepoint :
        # une erreur SQL avortée hors d'un `transaction.atomic()` dedie
        # laisserait la transaction (et le bloc `activate_tenant` englobant)
        # dans un etat casse pour le reste du test.
        with (
            pytest.raises(Exception, match="acc_move_balanced_when_posted"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute("UPDATE acc_move SET state = 'posted' WHERE id = %s", [str(move.id)])


def test_posted_move_is_immutable_even_via_raw_sql(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        move = _balanced_move(ledger)
        posted = post_move(move)

        with (
            pytest.raises(Exception, match="immuable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute("UPDATE acc_move SET narration = 'hack' WHERE id = %s", [str(posted.id)])


def test_posted_move_line_is_immutable(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        move = _balanced_move(ledger)
        posted = post_move(move)
        line = posted.lines.first()

        with (
            pytest.raises(Exception, match="immuable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute("UPDATE acc_move_line SET label = 'hack' WHERE id = %s", [str(line.id)])


def test_posting_in_a_closed_period_is_refused(ledger) -> None:
    tenant, _fy, period, *_ = ledger
    with use_tenant(tenant.id):
        period.state = AccPeriod.STATE_CLOSED
        period.save(update_fields=["state"])

        move = _balanced_move(ledger)
        with pytest.raises(ValidationError):
            post_move(move)


def test_sequence_numbering_has_no_gap_after_many_postings(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        references = []
        for _ in range(25):
            move = _balanced_move(ledger)
            posted = post_move(move)
            references.append(int(posted.reference.rsplit("-", 1)[-1]))

        assert references == list(range(references[0], references[0] + 25))


def test_reverse_move_creates_an_inverted_posted_entry(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        move = _balanced_move(ledger)
        posted = post_move(move)

        reversal = reverse_move(posted, motif="Erreur de saisie")

        assert reversal.state == AccMove.STATE_POSTED
        assert reversal.reverses_id == posted.id
        reversal_lines = {
            (line.account_id, line.debit, line.credit) for line in reversal.lines.all()
        }
        original_lines = {(line.account_id, line.credit, line.debit) for line in posted.lines.all()}
        assert reversal_lines == original_lines


def test_reverse_move_requires_a_motif(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        move = _balanced_move(ledger)
        posted = post_move(move)

        with pytest.raises(ValidationError):
            reverse_move(posted, motif="")
