"""Test d'acceptance §5.10.10 n°7 : la validation d'un lot de paie genere
une ecriture comptable equilibree (RG-PAY-8) — et Phase 3 §13.3 (ACC-9,
decision D5) : cette validation est desormais elle-meme bloquee tant que
les parametres reglementaires actifs qu'elle utilise n'ont pas ete
valides par un expert-comptable OECFM."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting.models import AccAccount, AccJournal, AccMove
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.regulatory import RegulatoryParameter
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip, PayPeriod
from apps.payroll.services.batches import control_batch, create_batch, validate_and_post_batch
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db


def _validate_all_regulatory_parameters(tenant: Tenant, user: User) -> None:
    """`seed_payroll_regulatory_params` ne fixe jamais `statut_validation`
    (il reste au defaut du modele, `STATUS_NON_VALIDE` — cf.
    `apps.core.tests.test_regulatory_deployment_gate.
    test_default_status_on_creation_is_non_valide`) : un test qui veut
    exercer une publication de lot REUSSIE doit valider explicitement les
    parametres qu'elle a seedes, comme le ferait un expert-comptable OECFM
    en conditions reelles — jamais lever cette exigence par un raccourci
    de test (cf. decision D5, aucune hypothese reglementaire ne peut etre
    levee par defaut)."""
    for parameter in RegulatoryParameter.objects.filter(tenant=tenant):
        parameter.mark_validated(user)


def test_batch_validation_posts_balanced_accounting_entry() -> None:
    tenant = Tenant.objects.create(code="PAY-RG8", name="RG-PAY-8")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_PAYROLL)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 3, 1), date_end=dt.date(2026, 3, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_PAYABLE)

        user = User.objects.create_user(email="rh-batch@example.com", password="Str0ngPassw0rd!23")
        _validate_all_regulatory_parameters(tenant, user)

        contract = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )
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
        # Raccourci de test : place directement la periode en "verifiee"
        # (le workflow complet `compute_period` -> `services.approvals.
        # request_period_verification` -> decision positive est teste
        # separement) — seule la comptabilisation RG-PAY-8 est ici sous
        # test.
        period.state = period.STATE_VERIFIED
        period.save(update_fields=["state"])

        batch = create_batch(period)
        anomalies = control_batch(batch, user)
        validate_and_post_batch(batch, user, force_despite_anomalies=bool(anomalies))

        payslip.refresh_from_db()
        assert payslip.move_id is not None
        move = AccMove.objects.get(id=payslip.move_id)
        assert move.state == AccMove.STATE_POSTED
        assert move.total_debit == move.total_credit
        assert move.total_debit > 0


def test_validate_and_post_batch_refuses_when_a_regulatory_parameter_is_not_validated() -> None:
    """Verrou OECFM (cahier Phase 3 §13.3, ACC-9, decision D5) — miroir de
    `apps.core.tests.test_regulatory_deployment_gate.
    test_non_valide_active_parameter_blocks_deployment`, applique ici au
    cycle de paie REEL plutot qu'a la seule commande de deploiement :
    `seed_payroll_regulatory_params` (via `setup_payroll_reference_data`)
    laisse volontairement les parametres au statut par defaut
    `STATUS_NON_VALIDE` — aucun appel a `mark_validated`, a la difference
    du test ci-dessus — donc la publication doit etre refusee, sans
    echappatoire (contrairement a `force_despite_anomalies`)."""
    tenant = Tenant.objects.create(code="PAY-D5", name="Verrou OECFM")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_PAYROLL)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 3, 1), date_end=dt.date(2026, 3, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_PAYABLE)

        user = User.objects.create_user(email="rh-d5@example.com", password="Str0ngPassw0rd!23")

        contract = make_active_contract(
            tenant, employee_id=uuid.uuid4(), wage_base=Decimal("1200000")
        )
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

        batch = create_batch(period)
        anomalies = control_batch(batch, user)

        with pytest.raises(ValidationError):
            validate_and_post_batch(batch, user, force_despite_anomalies=bool(anomalies))

        payslip.refresh_from_db()
        assert payslip.move_id is None
        assert AccMove.objects.filter(tenant=tenant).count() == 0
        period.refresh_from_db()
        assert period.state != PayPeriod.STATE_VALIDATED
