"""RG-PAY-8 (comptabilisation) + PAY-CTRL1 (controles avant validation) —
cycle de vie d'un `PayBatch`."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

import apps.accounting.services.public as accounting_public
from apps.core.models.user import User
from apps.core.services.regulatory_governance import (
    PAYROLL_CALCULATION_PARAMETER_CODES,
    unvalidated_active_parameters,
)
from apps.core.services.workflow import attempt_transition
from apps.payroll.models import PayBatch, PayPayslip, PayPeriod
from apps.payroll.services.anomalies import Anomaly, detect_batch_anomalies
from apps.payroll.services.periods import validate_period
from apps.payroll.services.regularization import (
    WITHHOLDING_CODES,
    regularization_movement,
    regularization_withholdings,
)

logger = logging.getLogger(__name__)


def create_batch(period: PayPeriod) -> PayBatch:
    """Idempotent PAR PERIODE (Bloc E, E6) : un appel repete pour la MEME
    periode reutilise le `PayBatch` deja existant plutot que d'en creer un
    nouveau orphelin — necessaire pour qu'un cycle controle -> anomalies
    detectees -> acquittement -> nouvelle tentative de validation reste
    porte par LE MEME lot (et ses acquittements deja enregistres), cf.
    `acknowledge_anomaly`/`validate_and_post_batch` ci-dessous."""
    batch, _created = PayBatch.objects.get_or_create(tenant=period.tenant, period=period)
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
    """Totaux du lot en MOUVEMENTS (L14/PAY-9), jamais en valeurs pleines.

    Un bulletin rectificatif ne compte que pour son ecart face a
    l'original : l'original a deja ete comptabilise et paye. Sommer les
    valeurs pleines faisait apparaitre un second salaire complet dans les
    totaux du lot — et dans tout ce qui en decoule."""
    gross = social = net = Decimal(0)
    for payslip in batch.payslips.exclude(state=PayPayslip.STATE_CANCELLED):
        gross += regularization_movement(payslip, "gross")
        social += regularization_movement(payslip, "social_employee") + regularization_movement(
            payslip, "social_employer"
        )
        net += regularization_movement(payslip, "net_to_pay")
    return {"gross": gross, "social": social, "net": net}


def control_batch(batch: PayBatch, user: User) -> list[Anomaly]:
    """PAY-CTRL1 : execute les 7 controles deterministes — ne bloque JAMAIS
    a lui seul la transition `control()` (les anomalies restent
    consultables/arbitrables par l'appelant, ex. via l'ecran de controle),
    seule `validate_and_post_batch` refuse la validation en cas d'anomalie
    non acquittee (cf. son propre docstring).

    Idempotent sur la transition (Bloc E, E6) : un second appel sur un lot
    deja CONTROLE re-detecte simplement les anomalies (utile apres un
    acquittement partiel, avant une nouvelle tentative de validation) sans
    retenter `control()` (qui n'accepte que `draft -> controlled`, echouerait
    sinon)."""
    anomalies = detect_batch_anomalies(batch)
    if batch.state == PayBatch.STATE_DRAFT:
        attempt_transition(batch, "control", user)
        batch.save(update_fields=["state"])
    return anomalies


def _acknowledged_keys(batch: PayBatch) -> set[tuple[str, str]]:
    return {(a["payslip_id"], a["code"]) for a in batch.anomaly_acknowledgments}


def acknowledge_anomaly(
    batch: PayBatch, *, payslip_id: Any, code: str, reason: str, user: User
) -> None:
    """Bloc E, E6 (PAY-7) : acquittement PAR ANOMALIE (paire payslip_id +
    code de controle), motif OBLIGATOIRE — remplace l'ancien acquittement
    global (`force_despite_anomalies`, retire de `validate_and_post_batch`
    ci-dessous). Idempotent par (payslip_id, code) : un second acquittement
    de la MEME anomalie remplace le motif precedent plutot que d'empiler
    des doublons (la derniere justification fait foi)."""
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour acquitter une anomalie."))
    payslip_id_str = str(payslip_id)
    acknowledgments = [
        a
        for a in batch.anomaly_acknowledgments
        if not (a["payslip_id"] == payslip_id_str and a["code"] == code)
    ]
    acknowledgments.append(
        {
            "payslip_id": payslip_id_str,
            "code": code,
            "reason": reason,
            "acknowledged_by": str(user.id),
            "acknowledged_at": timezone.now().isoformat(),
        }
    )
    batch.anomaly_acknowledgments = acknowledgments
    batch.save(update_fields=["anomaly_acknowledgments"])


def list_batch_anomalies(batch: PayBatch) -> list[dict[str, Any]]:
    """Bloc E, E6 (PAY-7) : anomalies ACTUELLES du lot, chacune annotee de
    son statut d'acquittement — vue de lecture pour l'ecran/l'API
    d'acquittement. `validate_and_post_batch` refait son propre calcul
    (structurellement identique) plutot que de dependre d'un appel
    prealable a celle-ci, pour ne jamais se fier a un instantane perime."""
    acknowledged_keys = _acknowledged_keys(batch)
    return [
        {
            "payslip_id": anomaly.payslip_id,
            "code": anomaly.code,
            "message": anomaly.message,
            "acknowledged": (str(anomaly.payslip_id), anomaly.code) in acknowledged_keys,
        }
        for anomaly in detect_batch_anomalies(batch)
    ]


def validate_and_post_batch(batch: PayBatch, user: User) -> PayBatch:
    """RG-PAY-8 : valide le lot -> comptabilise IMMEDIATEMENT (une ecriture
    par periode, cf. `apps.accounting.services.public.
    post_payroll_batch_entry_from_source`, publiee et non laissee en
    brouillon — deviation assumee documentee dans ce gap) -> approuve
    chaque bulletin -> fait avancer la periode a "validee" (RG-PAY-10,
    irreversibilite au-dela de ce point).

    Verrou OECFM (cahier Phase 3 §13.3, ACC-9, decision D5) : refuse
    INCONDITIONNELLEMENT la publication si un `RegulatoryParameter`
    actuellement effectif, pour un des 9 codes de calcul actifs de la
    paie, porte encore le statut NON_VALIDE — meme verrou logique que
    `apps.core.management.commands.check_regulatory_validation` (verifie
    au deploiement), applique ici au moment reel de publication d'un cycle
    plutot qu'a la seule pipeline CI.

    PAY-CTRL1/Bloc E, E6 (PAY-7) : refuse la validation si des anomalies
    ACTUELLEMENT detectees n'ont pas toutes ete acquittees INDIVIDUELLEMENT
    (`acknowledge_anomaly`, motif obligatoire) — remplace l'ancien
    acquittement global (`force_despite_anomalies`, retire) : plus aucune
    echappatoire "tout ou rien", chaque anomalie doit etre explicitement
    examinee et justifiee."""
    # Perimetre PAIE explicite : ce verrou ne doit porter que sur les codes
    # que `compute_payslip` lit reellement. Sans ce filtre, il portait sur
    # tout le registre, et l'ajout de `tva.taux_normal` par L3 a refuse la
    # publication de tout lot de paie pour un taux de TVA (trouve par L12-3).
    blocking = unvalidated_active_parameters(
        tenants=[batch.tenant], codes=PAYROLL_CALCULATION_PARAMETER_CODES
    )
    if blocking:
        codes = sorted({row.code for row in blocking})
        raise ValidationError(
            _(
                "Publication refusée : %(count)d paramètre(s) réglementaire(s) actif(s) "
                "non validé(s) par un expert-comptable OECFM (%(codes)s)."
            )
            % {"count": len(blocking), "codes": ", ".join(codes)}
        )

    anomalies = detect_batch_anomalies(batch)
    acknowledged_keys = _acknowledged_keys(batch)
    unacknowledged = [a for a in anomalies if (str(a.payslip_id), a.code) not in acknowledged_keys]
    if unacknowledged:
        raise ValidationError(
            _(
                "%(count)d anomalie(s) non acquittée(s) (PAY-CTRL1) — validation refusée. "
                "Chaque anomalie doit être acquittée individuellement avec un motif."
            )
            % {"count": len(unacknowledged)}
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
        # L14/PAY-9 : chaque montant est un MOUVEMENT, pas une valeur
        # pleine. Un rectificatif ne porte que son ecart face a l'original,
        # deja comptabilise — sans quoi le lot postait un second salaire
        # complet. L'identite algebrique reste vraie sur les ecarts (elle
        # est lineaire), donc l'ecriture reste equilibree : verifie par
        # `test_pay10_journal_equality.py` et par le test de delta.
        retenues = regularization_withholdings(
            payslip,
            current=sum(
                payslip.lines.filter(code__in=WITHHOLDING_CODES).values_list("amount", flat=True),
                Decimal(0),
            ),
        )
        gross = regularization_movement(payslip, "gross")
        social_employee = regularization_movement(payslip, "social_employee")
        social_employer = regularization_movement(payslip, "social_employer")
        irsa = regularization_movement(payslip, "irsa")
        net_to_pay = regularization_movement(payslip, "net_to_pay")
        entries = [
            (gross, "Salaire brut"),
            (social_employer, "Charges patronales (CNaPS+OSTIE)"),
            (-net_to_pay, "Net a payer"),
            (-social_employee, "Cotisations salariales (CNaPS+OSTIE)"),
            (-irsa, "IRSA"),
            (-social_employer, "Charges patronales a reverser"),
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
    # L14/PAY-9 — QUATRIEME chemin d'argent, manque par la premiere passe
    # de ce lot et trouve par la reconnaissance adverse.
    #
    # Un rectificatif ne retient reellement que l'ECART (cf.
    # `validate_and_post_batch` et `services/mobile_money.py`). Decrementer
    # le solde de l'avance du montant PLEIN de sa ligne `RETENUE_AVANCE`
    # eteindrait donc la dette du salarie sans qu'un ariary soit retenu —
    # et pourrait faire passer l'avance en `settled` sans remboursement.
    withheld = regularization_withholdings(payslip, current=line.amount, codes=("RETENUE_AVANCE",))
    if withheld <= 0:
        # Correction a la baisse : on a retenu TROP sur l'original. Rendre
        # cet argent au salarie est une operation a part entiere (un
        # remboursement d'avance), pas une echeance negative que
        # `register_installment` saurait traiter — il ne sait
        # qu'augmenter le rembourse. On ne touche donc pas au solde
        # plutot que de le fausser dans l'autre sens, et on le dit.
        logger.warning(
            "Rectificatif %s : retenue d'avance en baisse (%s) — le solde de "
            "l'avance n'est PAS modifie. Un remboursement au salarie doit etre "
            "traite separement.",
            payslip.reference or payslip.pk,
            withheld,
        )
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
        share = (withheld * advance.remaining / total_remaining).quantize(Decimal("0.0001"))
        register_installment(advance, user, amount=min(share, advance.remaining))
