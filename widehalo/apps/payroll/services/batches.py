"""RG-PAY-8 (comptabilisation) + PAY-CTRL1 (controles avant validation) —
cycle de vie d'un `PayBatch`."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

import apps.accounting.services.public as accounting_public
from apps.core.models.user import User
from apps.core.services.workflow import attempt_transition
from apps.payroll.models import PayBatch, PayPayslip, PayPeriod
from apps.payroll.services.anomalies import Anomaly, detect_batch_anomalies
from apps.payroll.services.periods import validate_period


def create_batch(period: PayPeriod) -> PayBatch:
    batch = PayBatch.objects.create(tenant=period.tenant, period=period)
    payslips = PayPayslip.objects.filter(
        tenant=period.tenant, period=period, state=PayPayslip.STATE_COMPUTED
    )
    payslips.update(batch=batch)
    totals = _recompute_totals(batch)
    batch.total_gross = totals["gross"]
    batch.total_net = totals["net"]
    batch.total_social = totals["social"]
    batch.save(update_fields=["total_gross", "total_net", "total_social"])
    return batch


def _recompute_totals(batch: PayBatch) -> dict[str, Decimal]:
    gross = social = net = Decimal(0)
    for payslip in batch.payslips.exclude(state=PayPayslip.STATE_CANCELLED):
        gross += payslip.gross
        social += payslip.social_employee + payslip.social_employer
        net += payslip.net_to_pay
    return {"gross": gross, "social": social, "net": net}


def control_batch(batch: PayBatch, user: User) -> list[Anomaly]:
    """PAY-CTRL1 : execute les 7 controles deterministes — ne bloque JAMAIS
    a lui seul la transition `control()` (les anomalies restent
    consultables/arbitrables par l'appelant, ex. via l'ecran de controle),
    seule `validate_and_post_batch` refuse la validation en cas d'anomalie
    non acquittee (cf. son propre docstring)."""
    anomalies = detect_batch_anomalies(batch)
    attempt_transition(batch, "control", user)
    batch.save(update_fields=["state"])
    return anomalies


def validate_and_post_batch(
    batch: PayBatch, user: User, *, force_despite_anomalies: bool = False
) -> PayBatch:
    """RG-PAY-8 : valide le lot -> comptabilise IMMEDIATEMENT (une ecriture
    par periode, cf. `apps.accounting.services.public.
    post_payroll_batch_entry_from_source`, publiee et non laissee en
    brouillon — deviation assumee documentee dans ce gap) -> approuve
    chaque bulletin -> fait avancer la periode a "validee" (RG-PAY-10,
    irreversibilite au-dela de ce point).

    PAY-CTRL1 : refuse la validation si des anomalies non acquittees
    subsistent, SAUF `force_despite_anomalies=True` (decision explicite de
    l'appelant, ex. RH qui a examine et ecarte les alertes — le CDC ne
    precise pas de blocage dur, "avant validation" est interprete comme un
    garde-fou de premiere ligne, contournable en connaissance de cause,
    disclosed)."""
    anomalies = detect_batch_anomalies(batch)
    if anomalies and not force_despite_anomalies:
        raise ValidationError(
            _("%(count)d anomalie(s) détectée(s) (PAY-CTRL1) — validation refusée.")
            % {"count": len(anomalies)}
        )

    lines: list[dict[str, object]] = []
    for payslip in batch.payslips.exclude(state=PayPayslip.STATE_CANCELLED):
        analytic: dict[str, str] = {}
        if payslip.contract.department_id:
            analytic["department"] = str(payslip.contract.department_id)
        if payslip.contract.workshop_id:
            analytic["workshop"] = str(payslip.contract.workshop_id)
        label_prefix = payslip.reference or str(payslip.employee_id)

        # **Ecritures generees a partir des TOTAUX du bulletin (pas de
        # chaque `pay_payslip_line` prise individuellement)** — la
        # majorite des 17 lignes du moteur de regles (`SAL_BASE`,
        # `PRIME_TOTAL`, `BASE_COTISABLE`, `OT_EXEMPT`, `BASE_IMPOSABLE`,
        # `IRSA_BRUT`, `NET_IMPOSABLE`...) sont des ETAPES DE CALCUL
        # intermediaires (PAY-M4 : auditabilite ligne a ligne du DETAIL du
        # calcul), pas des postes comptables distincts — seuls `gross`/
        # `social_employee`/`social_employer`/`irsa`/`net_to_pay` (deja
        # denormalises sur `PayPayslip`) + les 2 retenues (`RETENUE_
        # ABSENCE`/`RETENUE_AVANCE`, qui ne le sont pas) portent une
        # realite comptable. Verifie algebriquement equilibre par
        # construction : `net_to_pay = gross - social_employee - irsa -
        # retenues`, donc `gross + social_employer` (debit) == `net_to_pay
        # + social_employee + irsa + social_employer + retenues` (credit).
        retenues = sum(
            payslip.lines.filter(code__in=["RETENUE_ABSENCE", "RETENUE_AVANCE"]).values_list(
                "amount", flat=True
            ),
            Decimal(0),
        )
        entries = [
            (payslip.gross, "Salaire brut"),
            (payslip.social_employer, "Charges patronales (CNaPS+OSTIE)"),
            (-payslip.net_to_pay, "Net a payer"),
            (-payslip.social_employee, "Cotisations salariales (CNaPS+OSTIE)"),
            (-payslip.irsa, "IRSA"),
            (-payslip.social_employer, "Charges patronales a reverser"),
            (-retenues, "Retenues (absences/avances)"),
        ]
        for amount, label in entries:
            if amount == 0:
                continue
            lines.append(
                {
                    "account_id": None,
                    "amount": amount,
                    "label": f"{label_prefix} — {label}",
                    "analytic_distribution": analytic or None,
                }
            )

    move_id = None
    if lines:
        move_id = accounting_public.post_payroll_batch_entry_from_source(
            tenant=batch.tenant,
            date=batch.period.payment_date,
            lines=lines,
            label=f"Paie {batch.period.code}",
        )

    attempt_transition(batch, "validate", user)
    batch.save(update_fields=["state"])

    for payslip in batch.payslips.exclude(state=PayPayslip.STATE_CANCELLED):
        if move_id is not None:
            payslip.move_id = move_id
            payslip.save(update_fields=["move_id"])
        _submit_and_approve_payslip(payslip, user)
        _register_advance_installments(payslip, user)

    validate_period(batch.period, user)
    return batch


def _submit_and_approve_payslip(payslip: PayPayslip, user: User) -> None:
    """Extrait en fonction dediee (parametre EXPLICITEMENT annote) : le
    garde-fou AST `tests/architecture/test_attempt_transition_saves_state.py`
    ne resout le modele FSM concerne que via l'annotation de type d'un
    PARAMETRE de fonction, jamais une simple variable de boucle."""
    attempt_transition(payslip, "submit_for_approval", user)
    payslip.save(update_fields=["state"])
    attempt_transition(payslip, "approve", user)
    payslip.save(update_fields=["state"])


def _register_advance_installments(payslip: PayPayslip, user: User) -> None:
    """A l'APPROBATION effective du bulletin (jamais a un simple recalcul
    en brouillon, RG-PAY-10) : decremente reellement le solde des avances
    en remboursement de l'employe, du montant de la ligne `RETENUE_AVANCE`
    deja retenue sur ce bulletin — **simplification assumee (disclosed)** :
    si l'employe a PLUSIEURS avances `REPAYING` simultanees, le montant
    total retenu (deja calcule tout englobe par `services.payslip.
    _pending_advance_installment`) est reparti PROPORTIONNELLEMENT a
    `remaining` de chacune, plutot qu'a une avance a la fois dans un ordre
    arbitraire."""
    from apps.payroll.models import PayAdvance
    from apps.payroll.services.advances import register_installment

    line = payslip.lines.filter(code="RETENUE_AVANCE").first()
    if line is None or line.amount <= 0:
        return
    advances = list(
        PayAdvance.objects.filter(
            tenant=payslip.tenant, employee_id=payslip.employee_id, state=PayAdvance.STATE_REPAYING
        )
    )
    total_remaining = sum((a.remaining for a in advances), Decimal(0))
    if total_remaining <= 0:
        return
    for advance in advances:
        share = (line.amount * advance.remaining / total_remaining).quantize(Decimal("0.0001"))
        register_installment(advance, user, amount=min(share, advance.remaining))
