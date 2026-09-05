"""PAY-9 (L14) — un bulletin rectificatif ne doit etre comptabilise et
paye qu'en DELTA.

**Ce que ces tests ferment n'etait pas une commodite manquante.**
`services/regularization.py` presentait la recopie integrale comme une
« portee assumee et disclosee », le rapprochement du delta restant « a la
charge du gestionnaire de paie ». La chaine reelle est plus grave :

1. `create_regularization` cree un `PayPayslip` ordinaire a l'etat
   `computed`, rattache a la periode CIBLE ;
2. `services.batches.create_batch(periode_cible)` ramasse TOUT bulletin
   `computed` de cette periode — donc le rectificatif ;
3. `_recompute_totals`, `validate_and_post_batch` et les deux generateurs
   de fichier de paiement lisaient les valeurs PLEINES ;
4. rien, nulle part, ne lisait `rectifies`.

Consequence : corriger une erreur de 50 000 Ar sur un bulletin de
1 200 000 Ar postait une SECONDE ecriture de salaire complet et ordonnait
un SECOND VIREMENT COMPLET au salarie. Ce n'est pas une reserve de
confort, c'est de l'argent qui sort deux fois.

Le bulletin garde ses valeurs pleines — un document remis a un salarie
doit porter son salaire reel. Seuls l'ecriture, les totaux du lot et les
fichiers de paiement raisonnent en mouvement.
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
from apps.payroll.models import PayAdvance, PayPayslip, PayPeriod
from apps.payroll.services.batches import (
    _register_advance_installments,
    acknowledge_anomaly,
    control_batch,
    create_batch,
    validate_and_post_batch,
)
from apps.payroll.services.mobile_money import generate_mobile_money_transfer_file
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.services.regularization import (
    create_regularization,
    regularization_movement,
)
from apps.payroll.tests.factories import (
    make_active_contract,
    make_period,
    setup_payroll_reference_data,
)

pytestmark = pytest.mark.django_db

WAGE_BASE = Decimal("1200000")


def _accounting(tenant: Tenant) -> None:
    AccJournalFactory(tenant=tenant, type=AccJournal.TYPE_PAYROLL)
    AccPeriodFactory(tenant=tenant, date_start=dt.date(2026, 1, 1), date_end=dt.date(2026, 12, 31))
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_EXPENSE)
    AccAccountFactory(tenant=tenant, type=AccAccount.TYPE_PAYABLE)


def _validated_original(
    tenant: Tenant,
    *,
    overtime: dict[str, str] | None = None,
    advance_remaining: Decimal | None = None,
) -> PayPayslip:
    """`overtime` est pose AVANT le calcul et l'approbation : un bulletin
    publie est immuable en base (declencheur
    `pay_payslip_reject_mutation_if_published`), et c'est tant mieux — la
    premiere version de ce test essayait de le corriger apres coup et
    s'est fait refuser par le depot."""
    setup_payroll_reference_data(tenant)
    contract = make_active_contract(tenant, employee_id=uuid.uuid4(), wage_base=WAGE_BASE)
    if advance_remaining is not None:
        # AVANT le calcul de l'original : c'est ce qui fait que l'original et
        # son rectificatif portent la MEME retenue d'avance, donc un ecart
        # nul — le scenario reel d'une correction sans effet sur l'avance.
        PayAdvance.objects.create(
            tenant=tenant,
            employee_id=contract.employee_id,
            date=dt.date(2026, 1, 15),
            amount=Decimal("300000"),
            remaining=advance_remaining,
            repayment_months=3,
            state=PayAdvance.STATE_REPAYING,
        )
    period = make_period(tenant)
    payslip = PayPayslip.objects.create(
        tenant=tenant,
        employee_id=contract.employee_id,
        contract=contract,
        period=period,
        date_from=period.date_from,
        date_to=period.date_to,
        payment_method=PayPayslip.PAYMENT_MOBILE_MONEY,
        overtime_hours=overtime or {},
    )
    compute_payslip(payslip)
    payslip.state = PayPayslip.STATE_APPROVED
    payslip.save(update_fields=["state"])
    period.state = PayPeriod.STATE_VALIDATED
    period.save(update_fields=["state"])
    return payslip


def _target_period(tenant: Tenant) -> PayPeriod:
    return make_period(
        tenant,
        code="2026-04",
        date_from=dt.date(2026, 4, 1),
        date_to=dt.date(2026, 4, 30),
        payment_date=dt.date(2026, 4, 30),
    )


def _corrected(tenant: Tenant, *, overtime: dict[str, str]) -> tuple[PayPayslip, PayPayslip]:
    """Un rectificatif reellement DIFFERENT de l'original : des heures
    supplementaires declarees apres coup. Sans difference, tous les
    montants seraient nuls et les assertions ne prouveraient rien."""
    user = User.objects.create_user(
        email=f"rh-{uuid.uuid4().hex[:6]}@x.com", password="Str0ngPassw0rd!23"
    )
    original = _validated_original(tenant)
    target = _target_period(tenant)
    regularization = create_regularization(
        original,
        target_period=target,
        reason="Heures supplementaires declarees apres cloture",
        user=user,
        overtime_hours=overtime,
    )
    return original, regularization


def test_the_regularization_keeps_its_full_values_on_the_payslip() -> None:
    """Le document dit ce qui est DU. Un bulletin affichant un brut de
    50 000 Ar la ou le salarie gagne 1 250 000 Ar serait faux."""
    tenant = Tenant.objects.create(code="PAY-L14-1", name="PAY-9 delta 1")
    with use_tenant(tenant.id):
        original, regularization = _corrected(tenant, overtime={"jour_ouvrable_30": "10"})

        assert regularization.gross > original.gross
        assert regularization.gross > Decimal("1000000")


def test_only_the_delta_is_booked_and_paid() -> None:
    """LE test du critere. Avant L14, l'ecriture de la periode cible
    portait le salaire COMPLET du rectificatif."""
    tenant = Tenant.objects.create(code="PAY-L14-2", name="PAY-9 delta 2")
    with use_tenant(tenant.id):
        _accounting(tenant)
        original, regularization = _corrected(tenant, overtime={"jour_ouvrable_30": "10"})
        user = User.objects.create_user(email="rh-l14-2@example.com", password="Str0ngPassw0rd!23")
        for parameter in RegulatoryParameter.objects.filter(tenant=tenant):
            parameter.mark_validated(user)

        target = regularization.period
        target.state = PayPeriod.STATE_VERIFIED
        target.save(update_fields=["state"])
        batch = create_batch(target)
        for anomaly in control_batch(batch, user):
            acknowledge_anomaly(
                batch,
                payslip_id=anomaly.payslip_id,
                code=anomaly.code,
                reason="Ecart attendu sur un rectificatif.",
                user=user,
            )
        validate_and_post_batch(batch, user)

        regularization.refresh_from_db()
        move = AccMove.objects.get(id=regularization.move_id)
        expected_gross_delta = regularization.gross - original.gross

        assert expected_gross_delta > 0
        # L'ecriture porte l'ECART, pas le salaire complet.
        gross_line = move.lines.get(label__endswith="Salaire brut")
        assert gross_line.debit == expected_gross_delta
        assert gross_line.debit < original.gross
        # Et elle reste equilibree : l'identite algebrique de la paie est
        # lineaire, donc vraie sur les ecarts comme sur les valeurs pleines.
        assert move.total_debit == move.total_credit

        # Le fichier de paiement ordonne le meme ecart, jamais un second
        # virement complet.
        csv_text = generate_mobile_money_transfer_file(batch, phone_by_employee={})
        expected_net_delta = regularization.net_to_pay - original.net_to_pay
        assert str(expected_net_delta) in csv_text
        assert str(regularization.net_to_pay) not in csv_text


def test_the_batch_totals_count_the_delta_too() -> None:
    """Les totaux denormalises du lot alimentent l'ecran et les rapports :
    les laisser en valeurs pleines afficherait une masse salariale
    doublee sur le mois de la regularisation."""
    tenant = Tenant.objects.create(code="PAY-L14-3", name="PAY-9 delta 3")
    with use_tenant(tenant.id):
        original, regularization = _corrected(tenant, overtime={"jour_ouvrable_30": "10"})

        batch = create_batch(regularization.period)

        # Relecture depuis la base : `compute_payslip` laisse en memoire des
        # valeurs a pleine precision, la colonne stocke 4 decimales — et
        # c'est la valeur STOCKEE que le lot a sommee.
        original.refresh_from_db()
        regularization.refresh_from_db()

        assert batch.total_gross == regularization.gross - original.gross
        assert batch.total_net == regularization.net_to_pay - original.net_to_pay
        # L'ordre de grandeur dit tout : un ecart de quelques dizaines de
        # milliers d'ariary, pas un second salaire complet.
        assert batch.total_gross < original.gross / 10


def test_a_downward_correction_produces_a_negative_movement() -> None:
    """Un trop-percu est une dette du salarie envers l'employeur. La
    ramener a zero la ferait disparaitre des livres — l'ecart negatif est
    donc conserve tel quel."""
    tenant = Tenant.objects.create(code="PAY-L14-4", name="PAY-9 delta 4")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-l14-4@example.com", password="Str0ngPassw0rd!23")
        # L'original portait des heures supplementaires qui n'existaient pas.
        original = _validated_original(tenant, overtime={"jour_ouvrable_30": "10"})
        target = _target_period(tenant)

        regularization = create_regularization(
            original,
            target_period=target,
            reason="Heures supplementaires saisies a tort",
            user=user,
            overtime_hours={},
        )

        movement = regularization_movement(regularization, "gross")
        assert movement < 0
        assert movement == regularization.gross - original.gross


def test_an_ordinary_payslip_still_moves_its_full_value() -> None:
    """La regle du delta ne doit s'appliquer QU'aux rectificatifs : un
    bulletin ordinaire garde son mouvement plein, sans quoi L14 casserait
    toute la paie."""
    tenant = Tenant.objects.create(code="PAY-L14-5", name="PAY-9 delta 5")
    with use_tenant(tenant.id):
        payslip = _validated_original(tenant)

        for field in ("gross", "social_employee", "social_employer", "irsa", "net_to_pay"):
            assert regularization_movement(payslip, field) == getattr(payslip, field)


def test_a_non_monetary_field_is_refused() -> None:
    """`taxable_base` est une base de calcul, jamais un montant verse :
    demander son mouvement est une erreur d'appel, pas un cas metier."""
    tenant = Tenant.objects.create(code="PAY-L14-6", name="PAY-9 delta 6")
    with use_tenant(tenant.id):
        payslip = _validated_original(tenant)

        with pytest.raises(ValueError, match="taxable_base"):
            regularization_movement(payslip, "taxable_base")


def test_the_advance_balance_only_drops_by_what_was_really_withheld() -> None:
    """QUATRIEME chemin d'argent, manque par la premiere passe de ce lot.

    `_register_advance_installments` decrementait le solde de l'avance du
    montant PLEIN de la ligne `RETENUE_AVANCE` du rectificatif. Or seul
    l'ECART est reellement retenu sur le bulletin : la dette du salarie
    s'eteignait donc sans qu'un ariary soit repris, et l'avance pouvait
    passer en `settled` sans avoir ete remboursee.

    Scenario : une avance de 300 000 Ar sur 3 mois. Le bulletin de mars en
    retient 100 000. Un rectificatif de mars cree en juin recalcule la meme
    retenue de 100 000 — mais l'ecart est NUL, donc le solde ne doit pas
    bouger d'un ariary."""
    tenant = Tenant.objects.create(code="PAY-L14-7", name="PAY-9 avance")
    with use_tenant(tenant.id):
        user = User.objects.create_user(email="rh-l14-7@example.com", password="Str0ngPassw0rd!23")
        original = _validated_original(tenant, advance_remaining=Decimal("200000"))
        advance = PayAdvance.objects.get(tenant=tenant, employee_id=original.employee_id)
        remaining_before = advance.remaining
        target = _target_period(tenant)

        regularization = create_regularization(
            original,
            target_period=target,
            reason="Correction sans effet sur la retenue d'avance",
            user=user,
        )
        _register_advance_installments(regularization, user)

        advance.refresh_from_db()
        # L'original et le rectificatif portent la MEME retenue d'avance :
        # l'ecart est nul, donc rien n'a ete retenu, donc le solde ne doit
        # pas bouger d'un ariary. Avant L14 il perdait une echeance entiere.
        assert original.lines.get(code="RETENUE_AVANCE").amount > 0
        assert advance.remaining == remaining_before
        assert advance.state == PayAdvance.STATE_REPAYING
