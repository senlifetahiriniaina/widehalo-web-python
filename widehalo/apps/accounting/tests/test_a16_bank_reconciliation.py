"""A16 — Rapprochement bancaire assiste par regles (`acc_reconcile_rule`),
import de relevés CSV. Cf. docstring de
`services/bank_reconciliation.py` pour la reserve legere sur le format CSV
placeholder et le renoncement documente au parsing OFX/PDF."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import (
    AccAccount,
    AccBankStatementLine,
    AccFiscalYear,
    AccJournal,
    AccPeriod,
    AccReconcileRule,
)
from apps.accounting.services.bank_reconciliation import (
    confirm_reconciliation,
    import_bank_statement,
    manual_match,
    suggest_matches,
    unmatched_or_suggested_lines,
)
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.core.models.tenant import Tenant
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _make_account(tenant, *, code, name, account_class, type):
    return AccAccount.objects.create(
        tenant=tenant, code=code, name=name, account_class=account_class, type=type
    )


@pytest.fixture
def bare_ledger():
    tenant = Tenant.objects.create(code="ACC-A16", name="Accounting A16 Tenant")
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
        bank = _make_account(
            tenant, code="512", name="Banque", account_class=5, type=AccAccount.TYPE_BANK
        )
        return tenant, fiscal_year, period, journal, bank


# ---------------------------------------------------------------------------
# Import CSV
# ---------------------------------------------------------------------------

_SAMPLE_CSV = (
    b"date,reference,label,amount,direction\n"
    b"2026-02-01,VIR-1,Virement client Rakoto,5000,in\n"
    b"2026-02-02,VIR-2,Prelevement loyer,2000,out\n"
)


def test_import_bank_statement_creates_unmatched_lines(bare_ledger) -> None:
    tenant, _fiscal_year, _period, _journal, bank = bare_ledger
    with use_tenant(tenant.id):
        lines = import_bank_statement(bank, _SAMPLE_CSV)

        assert len(lines) == 2
        batch_ids = {line.import_batch_id for line in lines}
        assert len(batch_ids) == 1
        assert all(line.state == AccBankStatementLine.STATE_UNMATCHED for line in lines)
        amounts = sorted(line.amount_mga for line in lines)
        assert amounts == [Decimal("2000"), Decimal("5000")]
        assert all(line.bank_account_id == bank.id for line in lines)


def test_import_bank_statement_rejects_an_invalid_direction(bare_ledger) -> None:
    tenant, _fiscal_year, _period, _journal, bank = bare_ledger
    with use_tenant(tenant.id):
        bad_csv = b"date,reference,label,amount,direction\n2026-02-01,VIR-1,X,5000,sideways\n"
        with pytest.raises(ValidationError):
            import_bank_statement(bank, bad_csv)


def test_import_bank_statement_rejects_a_non_bank_account(bare_ledger) -> None:
    tenant, _fiscal_year, _period, _journal, _bank = bare_ledger
    with use_tenant(tenant.id):
        expense = _make_account(
            tenant, code="601", name="Achats", account_class=6, type=AccAccount.TYPE_EXPENSE
        )
        with pytest.raises(ValidationError):
            import_bank_statement(expense, _SAMPLE_CSV)


# ---------------------------------------------------------------------------
# Moteur de regles : ambiguite jamais devinee
# ---------------------------------------------------------------------------


def test_amount_only_rule_never_guesses_between_two_equal_amount_candidates(bare_ledger) -> None:
    tenant, _fiscal_year, period, journal, bank = bare_ledger
    with use_tenant(tenant.id):
        equity = _make_account(
            tenant, code="101", name="Capital", account_class=1, type=AccAccount.TYPE_EQUITY
        )

        def post_bank_line(label):
            move = create_draft_move(
                tenant=tenant, journal=journal, period=period, date=dt.date(2026, 2, 1)
            )
            add_line(move, account=bank, label=label, debit=Decimal("5000"))
            add_line(move, account=equity, label="Contrepartie", credit=Decimal("5000"))
            post_move(move)

        post_bank_line("Virement client Rakoto")
        post_bank_line("Virement client Rabe")

        (statement_line,) = import_bank_statement(
            bank,
            b"date,reference,label,amount,direction\n"
            b"2026-02-01,VIR-1,Virement client Rakoto,5000,in\n",
        )

        AccReconcileRule.objects.create(
            tenant=tenant, name="Montant seul", match_on_amount=True, match_on_reference=False
        )

        suggested = suggest_matches(bank)

        assert suggested == []
        statement_line.refresh_from_db()
        assert statement_line.state == AccBankStatementLine.STATE_UNMATCHED
        assert statement_line.matched_move_line_id is None


def test_adding_match_on_reference_resolves_the_ambiguity(bare_ledger) -> None:
    tenant, _fiscal_year, period, journal, bank = bare_ledger
    with use_tenant(tenant.id):
        equity = _make_account(
            tenant, code="101", name="Capital", account_class=1, type=AccAccount.TYPE_EQUITY
        )

        def post_bank_line(label):
            move = create_draft_move(
                tenant=tenant, journal=journal, period=period, date=dt.date(2026, 2, 1)
            )
            add_line(move, account=bank, label=label, debit=Decimal("5000"))
            add_line(move, account=equity, label="Contrepartie", credit=Decimal("5000"))
            post_move(move)
            return move.lines.get(account=bank)

        target_line = post_bank_line("Virement client Rakoto")
        post_bank_line("Virement client Rabe")

        (statement_line,) = import_bank_statement(
            bank, b"date,reference,label,amount,direction\n2026-02-01,Rakoto,Virement,5000,in\n"
        )

        AccReconcileRule.objects.create(
            tenant=tenant,
            name="Montant + reference",
            match_on_amount=True,
            match_on_reference=True,
        )

        suggested = suggest_matches(bank)

        assert len(suggested) == 1
        assert suggested[0].id == statement_line.id
        assert suggested[0].matched_move_line_id == target_line.id
        assert suggested[0].state == AccBankStatementLine.STATE_RULE_SUGGESTED


def test_priority_tries_next_rule_when_the_first_rule_is_ambiguous(bare_ledger) -> None:
    tenant, _fiscal_year, period, journal, bank = bare_ledger
    with use_tenant(tenant.id):
        equity = _make_account(
            tenant, code="101", name="Capital", account_class=1, type=AccAccount.TYPE_EQUITY
        )

        def post_bank_line(label):
            move = create_draft_move(
                tenant=tenant, journal=journal, period=period, date=dt.date(2026, 2, 1)
            )
            add_line(move, account=bank, label=label, debit=Decimal("5000"))
            add_line(move, account=equity, label="Contrepartie", credit=Decimal("5000"))
            post_move(move)
            return move.lines.get(account=bank)

        target_line = post_bank_line("Virement client Rakoto")
        post_bank_line("Virement client Rabe")

        (statement_line,) = import_bank_statement(
            bank, b"date,reference,label,amount,direction\n2026-02-01,Rakoto,Virement,5000,in\n"
        )

        # Priorite haute (evaluee en premier) : ambigue -> ignoree.
        AccReconcileRule.objects.create(
            tenant=tenant,
            name="Montant seul (haute priorite)",
            match_on_amount=True,
            match_on_reference=False,
            priority=10,
        )
        # Priorite basse (evaluee ensuite) : resout l'ambiguite.
        AccReconcileRule.objects.create(
            tenant=tenant,
            name="Montant + reference (basse priorite)",
            match_on_amount=True,
            match_on_reference=True,
            priority=1,
        )

        suggested = suggest_matches(bank)

        assert len(suggested) == 1
        assert suggested[0].matched_move_line_id == target_line.id


def test_global_rule_applies_to_a_bank_account_with_no_scope(bare_ledger) -> None:
    tenant, _fiscal_year, period, journal, bank = bare_ledger
    with use_tenant(tenant.id):
        equity = _make_account(
            tenant, code="101", name="Capital", account_class=1, type=AccAccount.TYPE_EQUITY
        )
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 2, 1)
        )
        add_line(move, account=bank, label="Virement unique", debit=Decimal("3000"))
        add_line(move, account=equity, label="Contrepartie", credit=Decimal("3000"))
        post_move(move)
        target_line = move.lines.get(account=bank)

        (statement_line,) = import_bank_statement(
            bank,
            b"date,reference,label,amount,direction\n2026-02-01,VIR-3,Virement unique,3000,in\n",
        )

        AccReconcileRule.objects.create(
            tenant=tenant, name="Regle globale", bank_account=None, match_on_amount=True
        )

        suggested = suggest_matches(bank)

        assert len(suggested) == 1
        assert suggested[0].id == statement_line.id
        assert suggested[0].matched_move_line_id == target_line.id


# ---------------------------------------------------------------------------
# Confirmation humaine / rapprochement manuel
# ---------------------------------------------------------------------------


def test_confirm_reconciliation_requires_a_rule_suggestion_or_explicit_move_line(
    bare_ledger,
) -> None:
    tenant, _fiscal_year, period, journal, bank = bare_ledger
    with use_tenant(tenant.id):
        equity = _make_account(
            tenant, code="101", name="Capital", account_class=1, type=AccAccount.TYPE_EQUITY
        )
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 2, 1)
        )
        add_line(move, account=bank, label="Virement", debit=Decimal("1000"))
        add_line(move, account=equity, label="Contrepartie", credit=Decimal("1000"))
        post_move(move)
        target_line = move.lines.get(account=bank)

        (statement_line,) = import_bank_statement(
            bank, b"date,reference,label,amount,direction\n2026-02-01,VIR-1,Virement,1000,in\n"
        )

        with pytest.raises(ValidationError):
            confirm_reconciliation(statement_line)

        confirmed = confirm_reconciliation(statement_line, move_line=target_line)
        assert confirmed.state == AccBankStatementLine.STATE_MATCHED
        assert confirmed.matched_move_line_id == target_line.id


def test_confirm_reconciliation_accepts_a_rule_suggested_line(bare_ledger) -> None:
    tenant, _fiscal_year, period, journal, bank = bare_ledger
    with use_tenant(tenant.id):
        equity = _make_account(
            tenant, code="101", name="Capital", account_class=1, type=AccAccount.TYPE_EQUITY
        )
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 2, 1)
        )
        add_line(move, account=bank, label="Virement", debit=Decimal("1000"))
        add_line(move, account=equity, label="Contrepartie", credit=Decimal("1000"))
        post_move(move)

        (statement_line,) = import_bank_statement(
            bank, b"date,reference,label,amount,direction\n2026-02-01,VIR-1,Virement,1000,in\n"
        )
        AccReconcileRule.objects.create(tenant=tenant, name="Montant seul", match_on_amount=True)
        (suggested_line,) = suggest_matches(bank)
        assert suggested_line.state == AccBankStatementLine.STATE_RULE_SUGGESTED

        confirmed = confirm_reconciliation(suggested_line)
        assert confirmed.state == AccBankStatementLine.STATE_MATCHED

        assert unmatched_or_suggested_lines(bank) == []


def test_manual_match_without_any_rule(bare_ledger) -> None:
    tenant, _fiscal_year, period, journal, bank = bare_ledger
    with use_tenant(tenant.id):
        equity = _make_account(
            tenant, code="101", name="Capital", account_class=1, type=AccAccount.TYPE_EQUITY
        )
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 2, 1)
        )
        add_line(move, account=bank, label="Virement inhabituel", debit=Decimal("777"))
        add_line(move, account=equity, label="Contrepartie", credit=Decimal("777"))
        post_move(move)
        target_line = move.lines.get(account=bank)

        (statement_line,) = import_bank_statement(
            bank,
            b"date,reference,label,amount,direction\n2026-02-01,VIR-X,Sans rapport,777,in\n",
        )

        matched = manual_match(statement_line, target_line)
        assert matched.state == AccBankStatementLine.STATE_MATCHED
        assert matched.matched_move_line_id == target_line.id


def test_partner_matching_with_partner_id(bare_ledger) -> None:
    tenant, _fiscal_year, period, journal, bank = bare_ledger
    with use_tenant(tenant.id):
        equity = _make_account(
            tenant, code="101", name="Capital", account_class=1, type=AccAccount.TYPE_EQUITY
        )
        partner_a = uuid.uuid4()
        partner_b = uuid.uuid4()

        def post_bank_line(partner_id):
            move = create_draft_move(
                tenant=tenant, journal=journal, period=period, date=dt.date(2026, 2, 1)
            )
            add_line(
                move,
                account=bank,
                label="Virement",
                debit=Decimal("4000"),
                partner_id=partner_id,
            )
            add_line(move, account=equity, label="Contrepartie", credit=Decimal("4000"))
            post_move(move)
            return move.lines.get(account=bank)

        post_bank_line(partner_a)
        target_line = post_bank_line(partner_b)

        (statement_line,) = import_bank_statement(
            bank, b"date,reference,label,amount,direction\n2026-02-01,VIR-1,Virement,4000,in\n"
        )
        statement_line.partner_id = partner_b
        statement_line.save(update_fields=["partner_id"])

        AccReconcileRule.objects.create(
            tenant=tenant,
            name="Montant + tiers",
            match_on_amount=True,
            match_on_partner=True,
        )

        suggested = suggest_matches(bank)

        assert len(suggested) == 1
        assert suggested[0].matched_move_line_id == target_line.id


def test_already_reconciled_move_lines_are_not_offered_as_candidates(bare_ledger) -> None:
    tenant, _fiscal_year, period, journal, bank = bare_ledger
    with use_tenant(tenant.id):
        equity = _make_account(
            tenant, code="101", name="Capital", account_class=1, type=AccAccount.TYPE_EQUITY
        )
        move = create_draft_move(
            tenant=tenant, journal=journal, period=period, date=dt.date(2026, 2, 1)
        )
        add_line(move, account=bank, label="Virement", debit=Decimal("1500"))
        add_line(move, account=equity, label="Contrepartie", credit=Decimal("1500"))
        post_move(move)
        target_line = move.lines.get(account=bank)

        lines = import_bank_statement(
            bank,
            b"date,reference,label,amount,direction\n"
            b"2026-02-01,VIR-1,Virement,1500,in\n"
            b"2026-02-02,VIR-2,Virement,1500,in\n",
        )
        AccReconcileRule.objects.create(tenant=tenant, name="Montant seul", match_on_amount=True)

        first_pass = suggest_matches(bank)
        assert len(first_pass) == 1
        assert first_pass[0].matched_move_line_id == target_line.id

        second_pass = suggest_matches(bank)
        assert second_pass == []
        remaining_unmatched = AccBankStatementLine.objects.filter(
            id__in=[line.id for line in lines], state=AccBankStatementLine.STATE_UNMATCHED
        )
        assert remaining_unmatched.count() == 1
