"""Bloc E, E6 (PAY-7) : acquittement PAR anomalie (paire payslip_id+code),
motif obligatoire — remplace l'ancien acquittement global
(`force_despite_anomalies`, retire de `validate_and_post_batch`).
`create_batch`/`control_batch` idempotents par periode/lot, necessaires
pour qu'un cycle controle -> anomalies -> acquittement -> nouvelle
tentative de validation reste porte par LE MEME lot."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayBatch, PayPayslip
from apps.payroll.services.batches import (
    acknowledge_anomaly,
    control_batch,
    create_batch,
    list_batch_anomalies,
    validate_and_post_batch,
)
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db


def _batch_with_one_anomaly(tenant: Tenant, user: User) -> PayBatch:
    """`missing_previous_payslip` (controle 4) : un contrat deja actif
    avant le debut de la periode, sans aucun bulletin le mois precedent —
    meme scenario deja exploite par `test_batches.py`."""
    from apps.core.models.regulatory import RegulatoryParameter

    setup_payroll_reference_data(tenant)
    for parameter in RegulatoryParameter.objects.filter(tenant=tenant):
        parameter.mark_validated(user)
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
    payslip.state = PayPayslip.STATE_COMPUTED
    payslip.save(update_fields=["state"])
    period.state = period.STATE_VERIFIED
    period.save(update_fields=["state"])
    return create_batch(period)


def test_acknowledge_anomaly_requires_a_reason() -> None:
    tenant = Tenant.objects.create(code="PAY-E6-1", name="E6 reason required")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e6-1@example.com", password="Str0ngPassw0rd!23")
        batch = _batch_with_one_anomaly(tenant, user)
        anomalies = control_batch(batch, user)
        assert anomalies

        with pytest.raises(ValidationError):
            acknowledge_anomaly(
                batch,
                payslip_id=anomalies[0].payslip_id,
                code=anomalies[0].code,
                reason="",
                user=user,
            )


def test_acknowledge_anomaly_records_reason_and_actor() -> None:
    tenant = Tenant.objects.create(code="PAY-E6-2", name="E6 record")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e6-2@example.com", password="Str0ngPassw0rd!23")
        batch = _batch_with_one_anomaly(tenant, user)
        anomalies = control_batch(batch, user)
        anomaly = anomalies[0]

        acknowledge_anomaly(
            batch,
            payslip_id=anomaly.payslip_id,
            code=anomaly.code,
            reason="Nouvel employé, absence de bulletin antérieur normale.",
            user=user,
        )

        batch.refresh_from_db()
        assert len(batch.anomaly_acknowledgments) == 1
        record = batch.anomaly_acknowledgments[0]
        assert record["payslip_id"] == str(anomaly.payslip_id)
        assert record["code"] == anomaly.code
        assert record["reason"] == "Nouvel employé, absence de bulletin antérieur normale."
        assert record["acknowledged_by"] == str(user.id)
        assert record["acknowledged_at"]


def test_acknowledge_anomaly_is_idempotent_and_replaces_previous_reason() -> None:
    tenant = Tenant.objects.create(code="PAY-E6-3", name="E6 idempotent")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e6-3@example.com", password="Str0ngPassw0rd!23")
        batch = _batch_with_one_anomaly(tenant, user)
        anomalies = control_batch(batch, user)
        anomaly = anomalies[0]

        acknowledge_anomaly(
            batch,
            payslip_id=anomaly.payslip_id,
            code=anomaly.code,
            reason="Premier motif.",
            user=user,
        )
        acknowledge_anomaly(
            batch,
            payslip_id=anomaly.payslip_id,
            code=anomaly.code,
            reason="Motif corrigé.",
            user=user,
        )

        batch.refresh_from_db()
        assert len(batch.anomaly_acknowledgments) == 1
        assert batch.anomaly_acknowledgments[0]["reason"] == "Motif corrigé."


def test_validate_and_post_batch_blocks_on_unacknowledged_anomaly() -> None:
    tenant = Tenant.objects.create(code="PAY-E6-4", name="E6 blocks")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e6-4@example.com", password="Str0ngPassw0rd!23")
        batch = _batch_with_one_anomaly(tenant, user)
        control_batch(batch, user)

        with pytest.raises(ValidationError):
            validate_and_post_batch(batch, user)


def test_validate_and_post_batch_succeeds_once_all_anomalies_acknowledged() -> None:
    tenant = Tenant.objects.create(code="PAY-E6-5", name="E6 succeeds")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e6-5@example.com", password="Str0ngPassw0rd!23")
        batch = _batch_with_one_anomaly(tenant, user)
        anomalies = control_batch(batch, user)
        for anomaly in anomalies:
            acknowledge_anomaly(
                batch,
                payslip_id=anomaly.payslip_id,
                code=anomaly.code,
                reason="Examiné, situation normale.",
                user=user,
            )

        result = validate_and_post_batch(batch, user)
        assert result.state == PayBatch.STATE_VALIDATED


def test_list_batch_anomalies_flags_acknowledged_status() -> None:
    tenant = Tenant.objects.create(code="PAY-E6-6", name="E6 list")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e6-6@example.com", password="Str0ngPassw0rd!23")
        batch = _batch_with_one_anomaly(tenant, user)
        control_batch(batch, user)

        before = list_batch_anomalies(batch)
        assert before
        assert all(not a["acknowledged"] for a in before)

        anomaly = before[0]
        acknowledge_anomaly(
            batch,
            payslip_id=anomaly["payslip_id"],
            code=anomaly["code"],
            reason="Motif.",
            user=user,
        )

        after = list_batch_anomalies(batch)
        assert all(a["acknowledged"] for a in after)


def test_create_batch_is_idempotent_per_period() -> None:
    tenant = Tenant.objects.create(code="PAY-E6-7", name="E6 create idempotent")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        period = make_period(tenant)

        batch_1 = create_batch(period)
        batch_2 = create_batch(period)

        assert batch_1.id == batch_2.id
        assert PayBatch.objects.filter(tenant=tenant, period=period).count() == 1


def test_control_batch_is_idempotent_after_already_controlled() -> None:
    tenant = Tenant.objects.create(code="PAY-E6-8", name="E6 control idempotent")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-e6-8@example.com", password="Str0ngPassw0rd!23")
        batch = _batch_with_one_anomaly(tenant, user)

        control_batch(batch, user)
        batch.refresh_from_db()
        assert batch.state == PayBatch.STATE_CONTROLLED

        # Deuxieme appel : ne retente pas la transition FSM (qui
        # echouerait, `controlled -> controlled` n'etant pas une
        # transition valide), se contente de re-detecter les anomalies.
        anomalies_again = control_batch(batch, user)
        assert anomalies_again
        batch.refresh_from_db()
        assert batch.state == PayBatch.STATE_CONTROLLED
