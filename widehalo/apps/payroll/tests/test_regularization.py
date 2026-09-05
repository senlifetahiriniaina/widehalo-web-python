"""Bloc E, E7 (PAY-9) : `create_regularization` — seul point d'entrée
renseignant réellement `PayPayslip.rectifies` (jusqu'ici un champ mort,
cf. audit Phase 3). Un bulletin rectificatif est un NOUVEAU `PayPayslip`
rattaché à une période cible encore ouverte, jamais une modification en
place de l'original (RG-PAY-10)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError

from apps.core.models.chatter import ChatterMessage
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip, PayPeriod
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.services.regularization import create_regularization
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db


def _validated_original(tenant: Tenant) -> PayPayslip:
    """Raccourci de test (même patron que `test_periods_workflow.py`/
    `test_batches.py`) : place directement bulletin+période à l'état
    verrouillé cible sans rejouer tout le cycle verify->control->
    acknowledge->validate, hors sujet de ce test."""
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
    payslip.state = PayPayslip.STATE_APPROVED
    payslip.save(update_fields=["state"])
    period.state = PayPeriod.STATE_VALIDATED
    period.save(update_fields=["state"])
    return payslip


def _open_target_period(tenant: Tenant) -> PayPeriod:
    return make_period(
        tenant,
        code="2026-04",
        date_from=dt.date(2026, 4, 1),
        date_to=dt.date(2026, 4, 30),
        payment_date=dt.date(2026, 4, 30),
    )


def test_create_regularization_requires_a_reason() -> None:
    tenant = Tenant.objects.create(code="PAY-E7-1", name="E7 reason required")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e7-1@example.com", password="Str0ngPassw0rd!23")
        original = _validated_original(tenant)
        target_period = _open_target_period(tenant)

        with pytest.raises(ValidationError):
            create_regularization(original, target_period=target_period, reason="", user=user)


def test_create_regularization_refuses_when_original_period_not_validated() -> None:
    tenant = Tenant.objects.create(code="PAY-E7-2", name="E7 origin not locked")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        user = User.objects.create_user(email="rh-e7-2@example.com", password="Str0ngPassw0rd!23")
        contract = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )
        period = make_period(tenant)  # STATE_OPEN par defaut, jamais verrouillee.
        original = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=contract.employee_id,
            contract=contract,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        compute_payslip(original)
        target_period = _open_target_period(tenant)

        with pytest.raises(ValidationError):
            create_regularization(original, target_period=target_period, reason="Motif.", user=user)


def test_create_regularization_refuses_when_original_is_cancelled() -> None:
    """`cancel()` n'a pour source que draft/computed/to_approve, jamais
    approved (et depuis E9/PAY-8, un trigger DB l'empêcherait de toute
    façon une fois publié) — un bulletin annulé coexiste avec une
    période verrouillée en étant annulé AVANT publication, exclu du lot
    (`batch.payslips.exclude(state=CANCELLED)`, E6/E7) pendant que les
    AUTRES bulletins font passer la période à `validee`."""
    tenant = Tenant.objects.create(code="PAY-E7-3", name="E7 cancelled")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e7-3@example.com", password="Str0ngPassw0rd!23")
        setup_payroll_reference_data(tenant)
        contract = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )
        period = make_period(tenant)
        original = PayPayslip.objects.create(
            tenant=tenant,
            employee_id=contract.employee_id,
            contract=contract,
            period=period,
            date_from=period.date_from,
            date_to=period.date_to,
        )
        compute_payslip(original)
        original.state = PayPayslip.STATE_CANCELLED
        original.save(update_fields=["state"])
        period.state = PayPeriod.STATE_VALIDATED
        period.save(update_fields=["state"])
        target_period = _open_target_period(tenant)

        with pytest.raises(ValidationError):
            create_regularization(original, target_period=target_period, reason="Motif.", user=user)


def test_create_regularization_refuses_when_target_period_already_validated() -> None:
    tenant = Tenant.objects.create(code="PAY-E7-4", name="E7 target locked")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e7-4@example.com", password="Str0ngPassw0rd!23")
        original = _validated_original(tenant)
        target_period = _open_target_period(tenant)
        target_period.state = PayPeriod.STATE_VALIDATED
        target_period.save(update_fields=["state"])

        with pytest.raises(ValidationError):
            create_regularization(original, target_period=target_period, reason="Motif.", user=user)


def test_create_regularization_refuses_across_tenants() -> None:
    tenant = Tenant.objects.create(code="PAY-E7-5A", name="E7 tenant A")
    other_tenant = Tenant.objects.create(code="PAY-E7-5B", name="E7 tenant B")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e7-5@example.com", password="Str0ngPassw0rd!23")
        original = _validated_original(tenant)
    with use_tenant(other_tenant.id):
        foreign_target_period = _open_target_period(other_tenant)

    with use_tenant(tenant.id), pytest.raises(ValidationError):
        create_regularization(
            original, target_period=foreign_target_period, reason="Motif.", user=user
        )


def test_create_regularization_creates_computed_rectificatif_linked_to_original() -> None:
    tenant = Tenant.objects.create(code="PAY-E7-6", name="E7 happy path")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e7-6@example.com", password="Str0ngPassw0rd!23")
        original = _validated_original(tenant)
        target_period = _open_target_period(tenant)
        payslips_before = PayPayslip.objects.count()

        regularization = create_regularization(
            original, target_period=target_period, reason="Absence corrigée après paie.", user=user
        )

        assert PayPayslip.objects.count() == payslips_before + 1
        assert regularization.rectifies_id == original.id
        assert regularization.period_id == target_period.id
        assert regularization.tenant_id == tenant.id
        assert regularization.employee_id == original.employee_id
        assert regularization.date_from == original.date_from
        assert regularization.date_to == original.date_to
        assert regularization.state == PayPayslip.STATE_COMPUTED
        assert regularization.lines.exists()
        # Meme contrat/parametres que l'acceptance §5.10.10 n°1
        # (`test_rubric_simulation_view.py`) : aucune absence, aucune
        # heure sup — NET_A_PAYER identique attendu.
        assert "1033300" in str(regularization.net_to_pay)

        original.refresh_from_db()
        assert original.state == PayPayslip.STATE_APPROVED
        assert original.period_id != regularization.period_id


def test_create_regularization_records_reason_on_chatter() -> None:
    tenant = Tenant.objects.create(code="PAY-E7-7", name="E7 chatter")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e7-7@example.com", password="Str0ngPassw0rd!23")
        original = _validated_original(tenant)
        target_period = _open_target_period(tenant)

        regularization = create_regularization(
            original, target_period=target_period, reason="Correction motivée.", user=user
        )

        content_type = ContentType.objects.get_for_model(PayPayslip)
        message = ChatterMessage.objects.get(
            tenant_id=tenant.id, content_type=content_type, object_id=str(regularization.id)
        )
        assert message.body == "Correction motivée."
        assert message.is_note is True
        assert message.author_id == user.id


def test_create_regularization_applies_overtime_hours_override() -> None:
    tenant = Tenant.objects.create(code="PAY-E7-8", name="E7 override")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e7-8@example.com", password="Str0ngPassw0rd!23")
        original = _validated_original(tenant)
        target_period = _open_target_period(tenant)

        regularization = create_regularization(
            original,
            target_period=target_period,
            reason="Heures supplémentaires omises.",
            user=user,
            overtime_hours={"h_sup_30": "10.00"},
        )

        assert regularization.overtime_hours.get("h_sup_30") == "10.00"
