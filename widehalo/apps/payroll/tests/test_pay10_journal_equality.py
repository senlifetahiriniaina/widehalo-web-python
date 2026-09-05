"""P3/PAY-10 (L12-3) — le journal de paie publie egale la somme des
rubriques, a l'ariary pres.

Critere, mot pour mot : « Journal de paie d'un cycle publie se deversant
en une ecriture equilibree, somme des rubriques egale au total a l'ariary
pres. »

**Ce que ces tests ferment.** `test_batches.py::test_batch_validation_
posts_balanced_accounting_entry` n'assert que `move.total_debit ==
move.total_credit`. C'est une propriete plus faible qu'il n'y parait :
**une ecriture equilibree sur un mauvais montant reste equilibree.** Elle
ne dit rien de la somme des rubriques. `services/batches.py` affirme en
toutes lettres « Verifie algebriquement equilibre PAR CONSTRUCTION :
net_to_pay = gross - social_employee - irsa - retenues » — affirmation
jamais testee, et « par construction » est exactement le genre de preuve
que ce depot a deja vu se reveler fausse.

**Pourquoi ces tests prouvent quelque chose.** Ils remontent aux
`PayPayslipLine` — les rubriques elles-memes, produites par le moteur de
regles — et jamais aux seuls totaux denormalises de `PayPayslip`, qui sont
justement ce qu'il faut verifier. Le dernier test fausse deux totaux de
facon COMPENSEE : l'ecriture reste parfaitement equilibree, l'ancienne
assertion passe toujours, et seule la comparaison aux rubriques voit
l'erreur. C'est la demonstration que l'ancien test prouvait moins qu'il
n'y paraissait.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from apps.accounting.models import AccAccount, AccJournal, AccMove
from apps.accounting.tests.factories import AccAccountFactory, AccJournalFactory, AccPeriodFactory
from apps.core.models.regulatory import RegulatoryParameter
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.tests.utils import use_tenant
from apps.payroll.models import PayPayslip
from apps.payroll.services.batches import (
    acknowledge_anomaly,
    control_batch,
    create_batch,
    validate_and_post_batch,
)
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db

# Les rubriques telles que le moteur de regles les nomme
# (`fixtures/payroll_structure_mg.json`). Redeclarees ici plutot
# qu'importees : si la structure salariale change de code, ce test doit
# rougir plutot que suivre en silence.
GROSS_CODE = "BRUT"
EMPLOYEE_SOCIAL_CODES = ("CNAPS_SAL", "OSTIE_SAL")
EMPLOYER_SOCIAL_CODES = ("CNAPS_PAT", "OSTIE_PAT", "FMFP_PAT")
IRSA_CODE = "IRSA_NET"
NET_CODE = "NET_A_PAYER"
WITHHOLDING_CODES = ("RETENUE_ABSENCE", "RETENUE_AVANCE")


def _rubric(payslip: PayPayslip, *codes: str) -> Decimal:
    """Somme des rubriques du bulletin, lue sur les `PayPayslipLine` — le
    detail produit par le moteur de regles, jamais les totaux
    denormalises de `PayPayslip` qui sont precisement sous test."""
    return sum(
        payslip.lines.filter(code__in=codes).values_list("amount", flat=True),
        Decimal(0),
    )


def _posted_batch(tenant_code: str, *, wage_bases: list[Decimal]):
    """Cycle de paie complet, publie : parametres, structure salariale,
    contrats, bulletins calcules, lot controle et valide."""
    tenant = Tenant.objects.create(code=tenant_code, name=f"PAY-10 {tenant_code}")
    with use_tenant(tenant.id):
        setup_payroll_reference_data(tenant)
        AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_PAYROLL)
        AccPeriodFactory(
            tenant=tenant, date_start=dt.date(2026, 3, 1), date_end=dt.date(2026, 3, 31)
        )
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)
        AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_PAYABLE)

        user = User.objects.create_user(
            email=f"{tenant_code.lower()}@example.com", password="Str0ngPassw0rd!23"
        )
        for parameter in RegulatoryParameter.objects.filter(tenant=tenant):
            parameter.mark_validated(user)

        period = make_period(tenant)
        payslips = []
        for wage_base in wage_bases:
            contract = make_active_contract(tenant, employee_id=uuid.uuid4(), wage_base=wage_base)
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
            payslips.append(payslip)

        period.state = period.STATE_VERIFIED
        period.save(update_fields=["state"])
        return tenant, user, period, payslips


def _validate(batch, user):
    for anomaly in control_batch(batch, user):
        acknowledge_anomaly(
            batch,
            payslip_id=anomaly.payslip_id,
            code=anomaly.code,
            reason="Vérifié manuellement, aucune correction nécessaire.",
            user=user,
        )
    return validate_and_post_batch(batch, user)


def test_the_algebraic_identity_holds_on_the_rubrics_themselves() -> None:
    """`services/batches.py` affirme « net_to_pay = gross -
    social_employee - irsa - retenues », « verifie algebriquement par
    construction ». Jamais teste. Il l'est ici sur les RUBRIQUES, pas sur
    les totaux denormalises — les deux pourraient diverger, et c'est
    justement ce qu'il faut exclure."""
    tenant, _user, _period, payslips = _posted_batch("PAY10-ID", wage_bases=[Decimal("1200000")])
    with use_tenant(tenant.id):
        payslip = payslips[0]
        gross = _rubric(payslip, GROSS_CODE)
        social_employee = _rubric(payslip, *EMPLOYEE_SOCIAL_CODES)
        irsa = _rubric(payslip, IRSA_CODE)
        withholdings = _rubric(payslip, *WITHHOLDING_CODES)
        net = _rubric(payslip, NET_CODE)

        assert net == gross - social_employee - irsa - withholdings
        assert gross > 0  # sans quoi l'identite serait vraie sur du vide

        # Et les totaux denormalises, ceux que la comptabilisation lit,
        # sont bien ceux des rubriques.
        assert payslip.gross == gross
        assert payslip.social_employee == social_employee
        assert payslip.irsa == irsa
        assert payslip.net_to_pay == net
        assert payslip.social_employer == _rubric(payslip, *EMPLOYER_SOCIAL_CODES)


def test_the_journal_totals_equal_the_sum_of_the_rubrics_to_the_ariary() -> None:
    """Le critere lui-meme, sur un lot de DEUX bulletins : un seul ne
    ferait jamais apparaitre une erreur d'agregation."""
    tenant, user, period, payslips = _posted_batch(
        "PAY10-SUM", wage_bases=[Decimal("1200000"), Decimal("450000")]
    )
    with use_tenant(tenant.id):
        _validate(create_batch(period), user)

        moves = {p.id: p for p in payslips}
        for payslip in moves.values():
            payslip.refresh_from_db()
        move_ids = {p.move_id for p in moves.values()}
        assert len(move_ids) == 1 and None not in move_ids
        move = AccMove.objects.get(id=move_ids.pop())

        expected_debit = sum(
            (_rubric(p, GROSS_CODE) + _rubric(p, *EMPLOYER_SOCIAL_CODES) for p in moves.values()),
            Decimal(0),
        )
        expected_credit = sum(
            (
                _rubric(p, NET_CODE)
                + _rubric(p, *EMPLOYEE_SOCIAL_CODES)
                + _rubric(p, IRSA_CODE)
                + _rubric(p, *EMPLOYER_SOCIAL_CODES)
                + _rubric(p, *WITHHOLDING_CODES)
                for p in moves.values()
            ),
            Decimal(0),
        )

        assert move.total_debit == expected_debit
        assert move.total_credit == expected_credit
        assert move.total_debit == move.total_credit
        assert move.state == AccMove.STATE_POSTED


def test_a_balanced_entry_on_a_wrong_amount_is_caught_only_by_the_rubrics() -> None:
    """LE test qui donne sa valeur aux deux autres.

    On fausse deux totaux denormalises de facon COMPENSEE (`irsa` +X,
    `social_employee` -X). Les deux etant au credit, l'ecriture reste
    parfaitement equilibree : `total_debit == total_credit` passe toujours
    — l'assertion de `test_batches.py` ne voit rien. Seule la comparaison
    a la rubrique correspondante voit l'erreur.

    C'est la demonstration que « equilibree » ne veut pas dire « juste »,
    et donc que le critere PAY-10 demandait bien autre chose que ce qui
    etait teste."""
    tenant, user, period, payslips = _posted_batch("PAY10-FALSE", wage_bases=[Decimal("1200000")])
    with use_tenant(tenant.id):
        payslip = payslips[0]
        shift = Decimal("50000")
        payslip.irsa += shift
        payslip.social_employee -= shift
        payslip.save(update_fields=["irsa", "social_employee"])

        _validate(create_batch(period), user)
        payslip.refresh_from_db()
        move = AccMove.objects.get(id=payslip.move_id)

        # L'ancienne assertion passe toujours : rien n'est detecte.
        assert move.total_debit == move.total_credit

        # La ligne d'IRSA du journal ne correspond plus a la rubrique.
        irsa_line = move.lines.get(label__endswith="IRSA")
        assert irsa_line.credit != _rubric(payslip, IRSA_CODE)
        assert irsa_line.credit == _rubric(payslip, IRSA_CODE) + shift
