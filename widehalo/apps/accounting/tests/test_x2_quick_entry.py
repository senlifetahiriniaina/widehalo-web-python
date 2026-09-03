"""X2 (Sprint 8 / L5, cf. docs/planning/2026-refonte-ux-sprints.md §5) :
saisie comptable rapide — `services/quick_entry.py` (suggestion de
contrepartie) et l'écran (`quick_entry_create`/`quick_entry_detail`),
qui délègue entièrement le cycle de vie à `services/moves.py` déjà testé
(`test_moves.py`) — ces tests couvrent uniquement ce que X2 ajoute."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.test import Client

from apps.accounting.models import AccAccount, AccMove
from apps.accounting.services.moves import add_line, create_draft_move, post_move
from apps.accounting.services.quick_entry import suggest_counterpart_account
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _client(tenant: Tenant) -> Client:
    user = User.objects.create_user(email="compta@example.com", password="Str0ngPassw0rd!23")
    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()
    return client


def test_suggest_counterpart_account_returns_none_without_history() -> None:
    tenant = Tenant.objects.create(code="X2-1", name="X2 Tenant 1")
    with use_tenant(tenant.id):
        account = AccAccountFactory(tenant=tenant)
        assert suggest_counterpart_account(tenant=tenant, account=account) is None


def test_suggest_counterpart_account_returns_most_frequent_co_occurrence() -> None:
    tenant = Tenant.objects.create(code="X2-2", name="X2 Tenant 2")
    with use_tenant(tenant.id):
        journal = AccJournalFactory(tenant=tenant)
        period = AccPeriodFactory(tenant=tenant)
        bank = AccAccountFactory(tenant=tenant, code="5120", type=AccAccount.TYPE_BANK)
        expense_a = AccAccountFactory(tenant=tenant, code="6010")
        expense_b = AccAccountFactory(tenant=tenant, code="6020")

        for expense, count in ((expense_a, 2), (expense_b, 1)):
            for _ in range(count):
                move = create_draft_move(
                    tenant=tenant, journal=journal, period=period, date="2026-01-15"
                )
                add_line(move, account=bank, credit=Decimal("100"))
                add_line(move, account=expense, debit=Decimal("100"))
                post_move(move)

        suggested = suggest_counterpart_account(tenant=tenant, account=bank)
        assert suggested == expense_a


def test_suggest_counterpart_account_counts_distinct_entries_not_raw_lines() -> None:
    """Régression : une jointure `move__lines__account=account` naïve
    gonfle le compte d'une contrepartie proportionnellement au nombre de
    lignes que `account` porte sur la MÊME écriture (fan-out de jointure).
    Une seule écriture avec 2 lignes sur `bank` et 1 ligne sur
    `expense_a` doit compter pour 1 occurrence de `expense_a`, jamais 2 —
    sinon `expense_a` l'emporterait ici sur `expense_b` malgré 2 écritures
    distinctes réellement associées à `expense_b`."""
    tenant = Tenant.objects.create(code="X2-2B", name="X2 Tenant 2B")
    with use_tenant(tenant.id):
        journal = AccJournalFactory(tenant=tenant)
        period = AccPeriodFactory(tenant=tenant)
        bank = AccAccountFactory(tenant=tenant, code="5121", type=AccAccount.TYPE_BANK)
        expense_a = AccAccountFactory(tenant=tenant, code="6011")
        expense_b = AccAccountFactory(tenant=tenant, code="6021")

        move = create_draft_move(tenant=tenant, journal=journal, period=period, date="2026-01-15")
        add_line(move, account=bank, credit=Decimal("50"))
        add_line(move, account=bank, credit=Decimal("50"))
        add_line(move, account=expense_a, debit=Decimal("100"))
        post_move(move)

        for _ in range(2):
            move_b = create_draft_move(
                tenant=tenant, journal=journal, period=period, date="2026-01-16"
            )
            add_line(move_b, account=bank, credit=Decimal("10"))
            add_line(move_b, account=expense_b, debit=Decimal("10"))
            post_move(move_b)

        suggested = suggest_counterpart_account(tenant=tenant, account=bank)
        assert suggested == expense_b


def test_quick_entry_create_view_creates_a_draft_move() -> None:
    tenant = Tenant.objects.create(code="X2-3", name="X2 Tenant 3")
    with use_tenant(tenant.id):
        journal = AccJournalFactory(tenant=tenant)
        period = AccPeriodFactory(tenant=tenant)
    client = _client(tenant)

    response = client.post(
        "/accounting/quick-entry/new/",
        {
            "journal_id": str(journal.id),
            "period_id": str(period.id),
            "date": "2026-01-15",
            "narration": "Regularisation caisse",
        },
    )

    assert response.status_code == 302
    with use_tenant(tenant.id):
        move = AccMove.objects.get(tenant=tenant, move_type=AccMove.TYPE_ENTRY)
        assert move.state == AccMove.STATE_DRAFT
        assert move.narration == "Regularisation caisse"


def test_quick_entry_detail_add_line_then_post_balances_and_publishes() -> None:
    tenant = Tenant.objects.create(code="X2-4", name="X2 Tenant 4")
    with use_tenant(tenant.id):
        journal = AccJournalFactory(tenant=tenant)
        period = AccPeriodFactory(tenant=tenant)
        bank = AccAccountFactory(tenant=tenant, code="5120", type=AccAccount.TYPE_BANK)
        expense = AccAccountFactory(tenant=tenant, code="6010")
        move = create_draft_move(tenant=tenant, journal=journal, period=period, date="2026-01-20")
    client = _client(tenant)

    url = f"/accounting/quick-entry/{move.id}/"
    client.post(
        url, {"action": "add_line", "account_id": str(expense.id), "debit": "500", "credit": "0"}
    )
    client.post(
        url, {"action": "add_line", "account_id": str(bank.id), "debit": "0", "credit": "500"}
    )
    response = client.post(url, {"action": "post"})

    assert response.status_code == 302
    move.refresh_from_db()
    assert move.state == AccMove.STATE_POSTED
    assert move.total_debit == Decimal("500")
    assert move.total_credit == Decimal("500")
    assert move.reference


def test_quick_entry_detail_shows_error_when_posting_unbalanced_entry() -> None:
    tenant = Tenant.objects.create(code="X2-5", name="X2 Tenant 5")
    with use_tenant(tenant.id):
        journal = AccJournalFactory(tenant=tenant)
        period = AccPeriodFactory(tenant=tenant)
        expense = AccAccountFactory(tenant=tenant)
        move = create_draft_move(tenant=tenant, journal=journal, period=period, date="2026-01-20")
    client = _client(tenant)

    url = f"/accounting/quick-entry/{move.id}/"
    client.post(
        url, {"action": "add_line", "account_id": str(expense.id), "debit": "300", "credit": "0"}
    )
    response = client.post(url, {"action": "post"})

    assert response.status_code == 200
    move.refresh_from_db()
    assert move.state == AccMove.STATE_DRAFT
    assert response.context["error"]
