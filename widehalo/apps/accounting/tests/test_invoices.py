from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError

from apps.accounting.models import AccAccount, AccFiscalYear, AccJournal, AccMove, AccPeriod
from apps.accounting.services.invoices import (
    ApprovalRequiredError,
    cancel_invoice,
    create_invoice,
    create_supplier_invoice,
    ensure_default_approval_thresholds,
    validate_invoice,
)
from apps.core.models.audit import AuditLog
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.models.workflow import ApprovalRequest
from apps.core.services.approvals import decide
from apps.core.services.workflow import TransitionPermissionError, attempt_transition
from apps.core.tests.utils import use_tenant

pytestmark = pytest.mark.django_db


def _grant(user: User, group_name: str, *codenames: str) -> None:
    group, _ = Group.objects.get_or_create(name=group_name)
    for codename in codenames:
        permission = Permission.objects.get(codename=codename, content_type__app_label="accounting")
        group.permissions.add(permission)
    user.groups.add(group)


@pytest.fixture
def ledger():
    tenant = Tenant.objects.create(code="ACC-INV", name="Accounting Invoices Tenant")
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
            code="VTE",
            name="Ventes",
            type=AccJournal.TYPE_SALE,
            sequence_prefix="VTE",
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
        ensure_default_approval_thresholds(tenant)
        return tenant, period, journal, receivable, income


def _make_invoice(ledger, amount: Decimal):
    tenant, period, journal, receivable, income = ledger
    return create_invoice(
        tenant=tenant,
        journal=journal,
        period=period,
        date=dt.date(2026, 1, 15),
        partner_id=None,
        receivable_account=receivable,
        income_lines=[{"account": income, "amount": amount, "label": "Vente"}],
    )


def test_create_invoice_is_balanced(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        invoice = _make_invoice(ledger, Decimal("1000"))
        totals = {line.debit for line in invoice.lines.all() if line.debit} | {
            line.credit for line in invoice.lines.all() if line.credit
        }
        assert totals == {Decimal("1000")}


def test_validate_invoice_under_threshold_posts_directly(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="comptable@example.com", password="Str0ngPassw0rd!23")
        _grant(user, "comptable", "validate_accmove")

        invoice = _make_invoice(ledger, Decimal("500000"))
        posted = validate_invoice(invoice, user)

        assert posted.state == AccMove.STATE_POSTED
        assert posted.invoice_state == AccMove.INVOICE_STATE_VALIDATED
        assert posted.reference != ""


def test_validate_invoice_without_permission_is_refused(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="nobody@example.com", password="Str0ngPassw0rd!23")
        invoice = _make_invoice(ledger, Decimal("500000"))

        with pytest.raises(TransitionPermissionError):
            validate_invoice(invoice, user)


def test_validate_invoice_between_thresholds_requires_double_validation(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        comptable = User.objects.create_user(email="c2@example.com", password="Str0ngPassw0rd!23")
        _grant(comptable, "comptable", "validate_accmove")
        resp_commercial = User.objects.create_user(
            email="rc@example.com", password="Str0ngPassw0rd!23"
        )
        Group.objects.get_or_create(name="resp_commercial")[0].user_set.add(resp_commercial)

        invoice = _make_invoice(ledger, Decimal("5000000"))  # entre 2M et 10M

        with pytest.raises(ApprovalRequiredError):
            validate_invoice(invoice, comptable)

        first_request = ApprovalRequest.objects.get(
            object_id=str(invoice.id), rule__approver_role="comptable"
        )
        decide(first_request, comptable, approved=True)

        with pytest.raises(ApprovalRequiredError):
            validate_invoice(invoice, comptable)

        second_request = ApprovalRequest.objects.get(
            object_id=str(invoice.id), rule__approver_role="resp_commercial"
        )
        decide(second_request, resp_commercial, approved=True)

        posted = validate_invoice(invoice, comptable)
        assert posted.state == AccMove.STATE_POSTED


def test_validate_invoice_rejected_by_an_approver_raises(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        comptable = User.objects.create_user(email="c3@example.com", password="Str0ngPassw0rd!23")
        _grant(comptable, "comptable", "validate_accmove")

        invoice = _make_invoice(ledger, Decimal("5000000"))

        with pytest.raises(ApprovalRequiredError):
            validate_invoice(invoice, comptable)

        first_request = ApprovalRequest.objects.get(
            object_id=str(invoice.id), rule__approver_role="comptable"
        )
        decide(first_request, comptable, approved=False)

        with pytest.raises(ValidationError):
            validate_invoice(invoice, comptable)


def test_cancel_draft_invoice_requires_motif_and_permission(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        comptable = User.objects.create_user(email="c4@example.com", password="Str0ngPassw0rd!23")
        _grant(comptable, "comptable", "cancel_accmove")

        invoice = _make_invoice(ledger, Decimal("1000"))

        with pytest.raises(ValidationError):
            cancel_invoice(invoice, comptable, motif="")

        cancelled = cancel_invoice(invoice, comptable, motif="Erreur de saisie")
        assert cancelled.invoice_state == AccMove.INVOICE_STATE_CANCELLED


def test_cancel_posted_invoice_is_refused(ledger) -> None:
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        comptable = User.objects.create_user(email="c5@example.com", password="Str0ngPassw0rd!23")
        _grant(comptable, "comptable", "validate_accmove", "cancel_accmove")

        invoice = _make_invoice(ledger, Decimal("1000"))
        posted = validate_invoice(invoice, comptable)

        with pytest.raises(ValidationError):
            cancel_invoice(posted, comptable, motif="Trop tard")


def test_cancel_invoice_while_awaiting_double_validation(ledger) -> None:
    """Arete `to_validate -> cancelled` (RG-ACC couche 11) : la couche
    service actuelle ne laisse jamais une facture *persistee* en
    `to_validate` (`submit_for_validation()` et `validate()` s'enchainent
    dans le meme appel une fois toutes les approbations decidees) — cet etat
    n'est donc observable que via une transition directe du modele, ce que
    ce test verifie explicitement pour garder l'arete couverte. Une fois
    dans cet etat, `cancel_invoice` (garde-fou base sur `AccMove.state`, pas
    `invoice_state`) ne doit pas s'y opposer."""
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        comptable = User.objects.create_user(email="c6@example.com", password="Str0ngPassw0rd!23")
        _grant(comptable, "comptable", "validate_accmove", "cancel_accmove")

        invoice = _make_invoice(ledger, Decimal("1000"))
        invoice.submit_for_validation()
        invoice.save(update_fields=["invoice_state"])
        assert invoice.invoice_state == AccMove.INVOICE_STATE_TO_VALIDATE

        cancelled = cancel_invoice(invoice, comptable, motif="Commande annulee par le client")
        assert cancelled.invoice_state == AccMove.INVOICE_STATE_CANCELLED


def test_invoice_state_edges_not_reached_via_service_layer(ledger) -> None:
    """Aretes du graphe `AccMove.invoice_state` jamais declenchees par la
    couche service actuelle (`mark_paid_partially` depuis `overdue`,
    `mark_paid`/`mark_overdue` depuis les etats intermediaires,
    `mark_in_dispute`) : le modele les expose neanmoins et doivent rester
    couvertes pour eviter toute regression silencieuse si un futur job de
    detection des retards de paiement venait les exercer."""
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="c7@example.com", password="Str0ngPassw0rd!23")
        _grant(user, "comptable", "validate_accmove")

        invoice = _make_invoice(ledger, Decimal("1000"))
        validate_invoice(invoice, user)
        invoice.refresh_from_db()
        assert invoice.invoice_state == AccMove.INVOICE_STATE_VALIDATED

        # validated -> overdue
        attempt_transition(invoice, "mark_overdue", user)
        invoice.save(update_fields=["invoice_state"])
        assert invoice.invoice_state == AccMove.INVOICE_STATE_OVERDUE

        # overdue -> in_dispute
        attempt_transition(invoice, "mark_in_dispute", user)
        invoice.save(update_fields=["invoice_state"])
        assert invoice.invoice_state == AccMove.INVOICE_STATE_IN_DISPUTE


def test_invoice_paid_partially_from_overdue_and_paid_from_overdue(ledger) -> None:
    """Aretes `overdue -> paid_partially` et `overdue -> paid`."""
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="c8@example.com", password="Str0ngPassw0rd!23")
        _grant(user, "comptable", "validate_accmove")

        invoice = _make_invoice(ledger, Decimal("1000"))
        validate_invoice(invoice, user)
        invoice.refresh_from_db()
        attempt_transition(invoice, "mark_overdue", user)
        invoice.save(update_fields=["invoice_state"])
        assert invoice.invoice_state == AccMove.INVOICE_STATE_OVERDUE

        attempt_transition(invoice, "mark_paid_partially", user)
        invoice.save(update_fields=["invoice_state"])
        assert invoice.invoice_state == AccMove.INVOICE_STATE_PAID_PARTIALLY

        attempt_transition(invoice, "mark_overdue", user)
        invoice.save(update_fields=["invoice_state"])
        assert invoice.invoice_state == AccMove.INVOICE_STATE_OVERDUE

        attempt_transition(invoice, "mark_paid", user)
        invoice.save(update_fields=["invoice_state"])
        assert invoice.invoice_state == AccMove.INVOICE_STATE_PAID


# ---------------------------------------------------------------------------
# B5 (Phase 3, ACH-9) : séparation des tâches réception/facture —
# `validate_invoice` refuse (et journalise) une auto-validation par
# l'utilisateur ayant réceptionné la marchandise (`AccMove.received_by_ids`,
# peuplé par `purchase.services.invoicing.record_supplier_invoice`).
# ---------------------------------------------------------------------------


@pytest.fixture
def supplier_ledger():
    tenant = Tenant.objects.create(code="ACC-INV-SUP", name="Accounting Supplier Invoices Tenant")
    with use_tenant(tenant.id):
        fiscal_year = AccFiscalYear.objects.create(
            tenant=tenant,
            code="FY2026-SUP",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 12, 31),
        )
        period = AccPeriod.objects.create(
            tenant=tenant,
            fiscal_year=fiscal_year,
            code="2026-01-SUP",
            date_start=dt.date(2026, 1, 1),
            date_end=dt.date(2026, 1, 31),
        )
        journal = AccJournal.objects.create(
            tenant=tenant,
            code="ACH",
            name="Achats",
            type=AccJournal.TYPE_PURCHASE,
            sequence_prefix="ACH",
        )
        payable = AccAccount.objects.create(
            tenant=tenant,
            code="401",
            name="Fournisseurs",
            account_class=4,
            type=AccAccount.TYPE_PAYABLE,
        )
        expense = AccAccount.objects.create(
            tenant=tenant, code="601", name="Achats", account_class=6, type=AccAccount.TYPE_EXPENSE
        )
        ensure_default_approval_thresholds(tenant)
        return tenant, period, journal, payable, expense


def _make_supplier_invoice(supplier_ledger, amount: Decimal, *, received_by_ids=None):
    tenant, period, journal, payable, expense = supplier_ledger
    return create_supplier_invoice(
        tenant=tenant,
        journal=journal,
        period=period,
        date=dt.date(2026, 1, 15),
        partner_id=None,
        payable_account=payable,
        expense_lines=[{"account": expense, "amount": amount, "label": "Achat"}],
        received_by_ids=received_by_ids,
    )


def test_validate_invoice_refuses_self_validation_after_receiving(supplier_ledger) -> None:
    """B5 : l'utilisateur ayant réceptionné ne peut pas valider la facture
    fournisseur correspondante — refusé ET journalisé (`AuditLog`), même
    discipline que STK-7 (`stocks.services.inventory.validate_inventory`)."""
    tenant, *_ = supplier_ledger
    with use_tenant(tenant.id):
        receiver = User.objects.create_user(
            email="receveur@example.com", password="Str0ngPassw0rd!23"
        )
        _grant(receiver, "comptable", "validate_accmove")

        invoice = _make_supplier_invoice(
            supplier_ledger, Decimal("1000"), received_by_ids=[receiver.id]
        )

        with pytest.raises(ValidationError):
            validate_invoice(invoice, receiver)

        invoice.refresh_from_db()
        assert invoice.invoice_state == AccMove.INVOICE_STATE_DRAFT
        assert invoice.state == AccMove.STATE_DRAFT

        entry = AuditLog.objects.filter(action="accounting.invoice.self_validate").get()
        assert entry.actor_id == receiver.id
        assert entry.object_id == str(invoice.id)


def test_validate_invoice_allows_a_different_validator(supplier_ledger) -> None:
    """Même dossier, mais validé par une personne DISTINCTE de celle qui a
    réceptionné — aucun refus."""
    tenant, *_ = supplier_ledger
    with use_tenant(tenant.id):
        receiver = User.objects.create_user(
            email="receveur2@example.com", password="Str0ngPassw0rd!23"
        )
        validator = User.objects.create_user(
            email="comptable-b5@example.com", password="Str0ngPassw0rd!23"
        )
        _grant(validator, "comptable", "validate_accmove")

        invoice = _make_supplier_invoice(
            supplier_ledger, Decimal("1000"), received_by_ids=[receiver.id]
        )

        posted = validate_invoice(invoice, validator)
        assert posted.state == AccMove.STATE_POSTED


def test_validate_invoice_never_blocked_for_invoices_without_received_by_ids(
    supplier_ledger,
) -> None:
    """`received_by_ids` reste vide `[]` pour toute facture qui n'est pas
    issue de `purchase.services.invoicing.record_supplier_invoice` (ex.
    une facture client, ou une facture fournisseur créée directement sans
    ce paramètre) — la garde B5 ne les concerne jamais."""
    tenant, *_ = supplier_ledger
    with use_tenant(tenant.id):
        user = User.objects.create_user(
            email="comptable-b5-2@example.com", password="Str0ngPassw0rd!23"
        )
        _grant(user, "comptable", "validate_accmove")

        invoice = _make_supplier_invoice(supplier_ledger, Decimal("1000"))
        assert invoice.received_by_ids == []

        posted = validate_invoice(invoice, user)
        assert posted.state == AccMove.STATE_POSTED


def test_invoice_forbidden_transition_from_draft_raises(ledger) -> None:
    """Transition interdite representative du graphe `invoice_state` : un
    brouillon (`draft`) ne peut pas passer directement a `paid` — aucune
    arete ne relie ces deux etats."""
    tenant, *_ = ledger
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="c9@example.com", password="Str0ngPassw0rd!23")
        invoice = _make_invoice(ledger, Decimal("1000"))
        assert invoice.invoice_state == AccMove.INVOICE_STATE_DRAFT

        with pytest.raises(TransitionPermissionError):
            attempt_transition(invoice, "mark_paid", user)
