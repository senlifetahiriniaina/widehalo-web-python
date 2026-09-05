"""Bloc E, E9 (PAY-8) : trigger d'immutabilité `pay_payslip`/
`pay_payslip_line` (`payroll.0005_payslip_immutability`) — patron
calqué sur `apps/quality/tests/test_structural_constraints.py`
(`qlt_recall_dossier`, D4) et `apps/stocks/tests/
test_structural_constraints.py` (`stk_move`, A5)."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.db import connection, transaction

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip, PayPayslipLine
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def tenant():
    t = Tenant.objects.create(code="PAY-SC", name="Payroll Structural Constraints Tenant")
    with use_tenant(t.id):
        yield t


@pytest.fixture
def user(tenant):
    with use_tenant(tenant.id):
        return User.objects.create_user(email="sc-pay@example.com", password="Str0ngPassw0rd!23")


def _computed_payslip(tenant: Tenant) -> PayPayslip:
    setup_payroll_reference_data(tenant)
    contract = make_active_contract(tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000"))
    period = make_period(tenant)
    payslip = PayPayslip.objects.create(
        tenant=tenant,
        employee_id=contract.employee_id,
        contract=contract,
        period=period,
        date_from=period.date_from,
        date_to=period.date_to,
    )
    compute_payslip(payslip)
    return payslip


def _approved_payslip(tenant: Tenant) -> PayPayslip:
    """Raccourci de test (même patron que `test_batches.py`) : place
    directement le bulletin à `approved` sans rejouer tout le cycle
    `submit_for_approval` -> `approve`, hors sujet de ce test."""
    payslip = _computed_payslip(tenant)
    payslip.state = PayPayslip.STATE_APPROVED
    payslip.save(update_fields=["state"])
    return payslip


def test_approved_payslip_is_immutable_even_via_raw_sql(tenant) -> None:
    """Contourne les gardes de service et tente directement le SQL — le
    trigger doit refuser, même pour le propriétaire de la table (même
    patron que `stocks.tests.test_structural_constraints::
    test_done_move_is_immutable_even_via_raw_sql`)."""
    with use_tenant(tenant.id):
        payslip = _approved_payslip(tenant)

        with (
            pytest.raises(Exception, match="immuable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE pay_payslip SET gross = %s WHERE id = %s",
                [Decimal("999999"), str(payslip.id)],
            )

        payslip.refresh_from_db()
        assert payslip.gross != Decimal("999999")


def test_approved_payslip_cannot_be_deleted_via_raw_sql(tenant) -> None:
    with use_tenant(tenant.id):
        payslip = _approved_payslip(tenant)

        with (
            pytest.raises(Exception, match="immuable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute("DELETE FROM pay_payslip WHERE id = %s", [str(payslip.id)])

        assert PayPayslip.objects.filter(pk=payslip.pk).exists()


def test_unpublished_payslip_can_still_be_mutated_via_raw_sql(tenant) -> None:
    """Contrôle négatif : un bulletin encore `draft` (jamais publié)
    reste mutable — même patron que `test_draft_move_can_still_be_
    mutated_via_raw_sql` (stocks)."""
    with use_tenant(tenant.id):
        payslip = _computed_payslip(tenant)
        assert payslip.state == PayPayslip.STATE_DRAFT

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE pay_payslip SET payment_reference = %s WHERE id = %s",
                ["REF-TEST", str(payslip.id)],
            )

        payslip.refresh_from_db()
        assert payslip.payment_reference == "REF-TEST"


def test_approved_payslip_bookkeeping_field_update_is_still_allowed(tenant) -> None:
    """Les champs de suivi communs `BaseModel` (`is_active`/`archived_at`
    via `soft_delete()`) restent modifiables — même choix assumé que
    `stk_move`/`acc_move`/`qlt_recall_dossier`."""
    with use_tenant(tenant.id):
        payslip = _approved_payslip(tenant)

        payslip.soft_delete()

        payslip.refresh_from_db()
        assert payslip.is_active is False


def test_approved_to_paid_transition_is_still_permitted_via_raw_sql(tenant) -> None:
    """Seule transition légitime après publication (`_mark_payslip_paid`,
    `apps.payroll.services.periods`) — le trigger doit l'autoriser
    explicitement alors même que `state` reste par ailleurs protégé."""
    with use_tenant(tenant.id):
        payslip = _approved_payslip(tenant)

        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("UPDATE pay_payslip SET state = 'paid' WHERE id = %s", [str(payslip.id)])

        payslip.refresh_from_db()
        assert payslip.state == PayPayslip.STATE_PAID


def test_approved_payslip_state_cannot_jump_to_an_arbitrary_value(tenant) -> None:
    """`approved -> paid` est la SEULE transition tolérée une fois publié
    — un retour en arrière (ou tout autre saut) reste rejeté même si
    `state` est la colonne modifiée."""
    with use_tenant(tenant.id):
        payslip = _approved_payslip(tenant)

        with (
            pytest.raises(Exception, match="immuable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE pay_payslip SET state = 'draft' WHERE id = %s", [str(payslip.id)]
            )

        payslip.refresh_from_db()
        assert payslip.state == PayPayslip.STATE_APPROVED


def test_published_payslip_line_is_immutable_even_via_raw_sql(tenant) -> None:
    with use_tenant(tenant.id):
        payslip = _approved_payslip(tenant)
        line = payslip.lines.first()
        assert line is not None

        with (
            pytest.raises(Exception, match="immuable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(
                "UPDATE pay_payslip_line SET amount = %s WHERE id = %s",
                [Decimal("999999"), str(line.id)],
            )

        line.refresh_from_db()
        assert line.amount != Decimal("999999")


def test_published_payslip_line_cannot_be_deleted_via_raw_sql(tenant) -> None:
    with use_tenant(tenant.id):
        payslip = _approved_payslip(tenant)
        line = payslip.lines.first()
        assert line is not None

        with (
            pytest.raises(Exception, match="immuable"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute("DELETE FROM pay_payslip_line WHERE id = %s", [str(line.id)])

        assert PayPayslipLine.objects.filter(pk=line.pk).exists()


def test_unpublished_payslip_lines_can_still_be_mutated_via_raw_sql(tenant) -> None:
    with use_tenant(tenant.id):
        payslip = _computed_payslip(tenant)
        line = payslip.lines.first()
        assert line is not None

        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE pay_payslip_line SET amount = %s WHERE id = %s",
                [Decimal("42"), str(line.id)],
            )

        line.refresh_from_db()
        assert line.amount == Decimal("42")


def test_compute_payslip_is_blocked_by_db_trigger_once_published(tenant) -> None:
    """Le seul garde existant contre un recalcul sur bulletin publié est
    un garde de SERVICE (`ensure_active_contract_for_recompute`,
    `apps.payroll.services.periods`), jamais vérifié par
    `compute_payslip` lui-même (cf. docstring de la migration 0005).
    Ce test appelle `compute_payslip` DIRECTEMENT sur un bulletin déjà
    approuvé, en contournant volontairement ce garde de service, pour
    prouver que le verrou base de données (le `DELETE` des lignes
    existantes, première étape de `compute_payslip`) empêche quand même
    la corruption — la preuve concrète que E9 ferme le trou identifié
    par l'audit Phase 3, pas seulement en théorie."""
    with use_tenant(tenant.id):
        payslip = _approved_payslip(tenant)
        original_net_to_pay = payslip.net_to_pay
        line_ids_before = set(payslip.lines.values_list("id", flat=True))
        assert line_ids_before

        with pytest.raises(Exception, match="immuable"):
            compute_payslip(payslip)

        payslip.refresh_from_db()
        assert payslip.net_to_pay == original_net_to_pay
        assert set(payslip.lines.values_list("id", flat=True)) == line_ids_before
