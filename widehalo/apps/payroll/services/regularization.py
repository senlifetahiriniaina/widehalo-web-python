"""Bloc E, E7 (PAY-9) : régularisation réellement utilisée — seul point
d'entrée qui renseigne `PayPayslip.rectifies` (jusqu'ici un champ mort,
cf. audit Phase 3 : « le mécanisme de régularisation existe comme champ
mais n'est utilisé par aucun service, API ou test »). Patron répliqué de
`apps.payroll.services.contracts.create_amendment` (E5, RG-PAY-6) : un
bulletin RECTIFICATIF est un NOUVEAU `PayPayslip` — jamais un `save()`
sur l'original (RG-PAY-10, docstring de classe `PayPayslip`) — recalculé
via `compute_payslip` déjà existant (aucune duplication de la chaîne de
calcul PAY-1).

Décision de conception (aucun texte source PAY-9 plus détaillé que la
ligne du plan Phase 3 n'existe dans ce dépôt, cf. recherche du sprint) :
le rectificatif est rattaché à une période CIBLE distincte de la période
d'origine (`target_period`, un paramètre explicite, jamais résolu
automatiquement) — jamais réinjecté dans la période déjà validée de
l'original, qui porte déjà une écriture comptable postée et immuable
(RG-PAY-8) qu'une réinjection romprait silencieusement, et qui
contiendrait sinon des bulletins à des états FSM incohérents entre eux
(l'original déjà `approved`/`paid`, un rectificatif encore `draft`).
C'est aussi le patron réel d'une régularisation de paie : une correction
constatée après coup est portée sur un cycle de paie ultérieur, jamais
réinjectée dans un cycle déjà clos.

`date_from`/`date_to` du rectificatif restent ceux de L'ORIGINAL (pas de
la période cible) : PAY-M3 exige que les paramètres réglementaires
soient résolus à la date de la période CORRIGÉE, jamais à la date de
traitement administratif — un rectificatif de mars traité en juin doit
appliquer le barème de mars, exactement comme le ferait un recalcul
normal si la période n'était pas verrouillée.

Le motif est obligatoire mais n'est PAS un nouveau champ de modèle
(aucun n'est annoncé par le plan Phase 3 pour E7, budget de modèles
inchangé, cf. `tests/architecture/test_budget.py`) : posté sur le fil de
discussion générique du nouveau bulletin
(`apps.core.services.chatter.post_message`, note interne), déjà protégé
par une garde RBAC dédiée réservant sa lecture au staff RH
(`apps.payroll.services.chatter_registration.register_chatter_guards`).

**Réserve levée par L14, et elle cachait un défaut d'argent.** Ce module
annonçait comme une commodité manquante que le rectificatif « recopie et
RECALCULE les valeurs de l'original plutôt que de ne calculer qu'un
DELTA », le rapprochement restant « à la charge du gestionnaire de paie ».
La conséquence réelle était autrement plus grave : le bulletin
rectificatif est un `PayPayslip` ordinaire à l'état `computed`, donc
`services.batches.create_batch` le ramasse dans le lot de la période
cible, et RIEN nulle part ne lisait `rectifies`. Le lot comptabilisait
donc un SECOND SALAIRE COMPLET, et les fichiers de paiement
(`services/mobile_money.py`) ordonnaient un SECOND VIREMENT COMPLET — là
où le salarié n'avait droit qu'à la différence.

`regularization_movement` ci-dessous donne le montant à BOUGER : la
différence face à l'original pour un rectificatif, la valeur pleine
sinon. Les trois chemins d'argent (totaux du lot, écriture comptable,
fichiers de paiement) passent par lui.

Le bulletin lui-même garde ses valeurs PLEINES, et c'est voulu : un
bulletin remis à un salarié doit porter son salaire réel, jamais un écart
de 50 000 Ar présenté comme un brut. Le document dit ce qui est dû ;
l'écriture et le virement disent ce qui bouge. C'est aussi la pratique
réelle d'une régularisation de paie."""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _

from apps.core.models.user import User
from apps.core.services.chatter import post_message
from apps.core.services.workflow import attempt_transition
from apps.payroll.models import PayPayslip, PayPeriod
from apps.payroll.services.payslip import compute_payslip
from apps.payroll.services.periods import ensure_active_contract_for_recompute

_REGULARIZABLE_ORIGIN_STATES = (
    PayPeriod.STATE_VALIDATED,
    PayPeriod.STATE_PAID,
    PayPeriod.STATE_CLOSED,
)


# `worked_days`/`worked_hours`/`absence_days` sont volontairement ABSENTS
# d'ici : ce sont des sorties de `compute_payslip` (recalculees
# inconditionnellement a partir de `presence_public.
# get_period_absence_summary` pour `date_from`/`date_to`, cf.
# `services.payslip.compute_payslip`), jamais des entrees — les copier
# depuis l'original serait immediatement ecrase, donc trompeur.
# `overtime_hours` reste la seule EXCEPTION reelle : lu comme entree par
# `compute_payslip` (`payslip.overtime_hours or None`) avant d'etre
# resserialise, donc un vrai candidat a override.
_COPIED_FIELDS = (
    "employee_id",
    "contract",
    "date_from",
    "date_to",
    "overtime_hours",
    "payment_method",
)


def _mark_regularization_computed(payslip: PayPayslip, user: User) -> None:
    """Meme contournement que `services.periods._mark_payslip_computed` :
    le garde-fou AST `tests/architecture/
    test_attempt_transition_saves_state.py` ne resout le modele FSM
    concerne que via l'annotation de type d'un PARAMETRE de fonction,
    jamais une simple variable locale."""
    attempt_transition(payslip, "mark_computed", user)
    payslip.save(update_fields=["state"])


# Rubriques de retenue portant une realite comptable (les autres lignes du
# moteur de regles sont des etapes de calcul intermediaires, cf.
# `services/batches.py`). Declarees ICI et importees par `batches.py`
# plutot que recopiees : la regle du delta doit s'appliquer exactement aux
# memes rubriques que la comptabilisation, sans quoi les deux divergeraient
# au premier ajout de rubrique.
WITHHOLDING_CODES = ("RETENUE_ABSENCE", "RETENUE_AVANCE")

# Champs monetaires d'un bulletin qui ont un sens de MOUVEMENT : ce sont
# eux qui alimentent l'ecriture comptable (`services/batches.py`) et les
# fichiers de paiement (`services/mobile_money.py`). `taxable_base` en est
# volontairement absent : c'est une base de calcul, jamais un montant
# verse ou comptabilise.
MOVEMENT_FIELDS = (
    "gross",
    "social_employee",
    "social_employer",
    "irsa",
    "net_to_pay",
)


def regularization_movement(payslip: PayPayslip, field: str) -> Decimal:
    """Montant a BOUGER pour ce bulletin sur ce champ (PAY-9, L14).

    Pour un bulletin ordinaire : la valeur pleine. Pour un RECTIFICATIF
    (`rectifies` renseigne) : la difference face au bulletin d'origine —
    l'original a deja ete comptabilise et paye, seul l'ecart reste du.

    Une difference NEGATIVE est un cas normal et attendu (correction a la
    baisse : trop-percu a reprendre), jamais ramenee a zero — la masquer
    ferait disparaitre une dette du salarie envers l'employeur.

    Le bulletin conserve ses valeurs pleines : cf. docstring de module
    pour pourquoi le document et le mouvement disent deux choses
    differentes."""
    if field not in MOVEMENT_FIELDS:
        raise ValueError(f"Champ non monetaire : {field!r}. Attendu parmi {MOVEMENT_FIELDS}.")
    value: Decimal = getattr(payslip, field)
    original = payslip.rectifies
    if original is None:
        return value
    previous: Decimal = getattr(original, field)
    return value - previous


def regularization_withholdings(
    payslip: PayPayslip,
    *,
    current: Decimal,
    codes: tuple[str, ...] = WITHHOLDING_CODES,
) -> Decimal:
    """Meme regle du delta, pour les retenues — qui ne sont pas
    denormalisees sur `PayPayslip` mais sommees depuis les
    `PayPayslipLine` par l'appelant, d'ou le parametre `current`.

    `codes` restreint le perimetre a un sous-ensemble de rubriques. Un seul
    appelant l'utilise : `batches._register_advance_installments`, qui ne
    raisonne que sur `RETENUE_AVANCE` — le solde d'une avance ne doit etre
    decremente que de ce qui a REELLEMENT ete retenu sur ce bulletin."""
    original = payslip.rectifies
    if original is None:
        return current
    previous = sum(
        original.lines.filter(code__in=codes).values_list("amount", flat=True),
        Decimal(0),
    )
    return current - previous


@transaction.atomic
def create_regularization(
    original: PayPayslip,
    *,
    target_period: PayPeriod,
    reason: str,
    user: User,
    dependents: int = 0,
    **overrides: object,
) -> PayPayslip:
    """RG-PAY-10 : crée et calcule le bulletin rectificatif de `original`,
    rattaché à `target_period` (cf. docstring de module pour le choix de
    conception) — jamais un `save()` sur `original`. `reason` est
    obligatoire, tracé au chatter du nouveau bulletin (jamais un nouveau
    champ de modèle, cf. docstring de module). `overrides` : champs
    explicitement corrigés (ex. `overtime_hours`, seule vraie entrée de
    `compute_payslip` parmi les champs copiés — cf. `_COPIED_FIELDS`
    ci-dessous), copiés de `original` sinon — même discipline que
    `create_amendment` (RG-PAY-6)."""
    if not reason:
        raise ValidationError(_("Un motif est obligatoire pour créer un bulletin rectificatif."))
    if original.state == PayPayslip.STATE_CANCELLED:
        raise ValidationError(_("Impossible de régulariser un bulletin annulé."))
    if original.period.state not in _REGULARIZABLE_ORIGIN_STATES:
        raise ValidationError(
            _(
                "Le bulletin d'origine appartient à une période pas encore "
                "validée : recalculez-le directement plutôt que de créer un "
                "rectificatif (RG-PAY-10)."
            )
        )
    if target_period.tenant_id != original.tenant_id:
        raise ValidationError(_("La période cible doit appartenir au même tenant."))
    # Ne verifie que l'etat de `target_period` (le parametre `contract`
    # n'est en realite jamais lu par cette fonction) — meme garde
    # reutilisee telle quelle par `recompute_payslip_endpoint`.
    ensure_active_contract_for_recompute(original.contract, target_period)

    fields: dict[str, object] = {name: getattr(original, name) for name in _COPIED_FIELDS}
    fields.update(overrides)
    fields["tenant"] = original.tenant
    fields["period"] = target_period
    fields["rectifies"] = original

    regularization = PayPayslip.objects.create(**fields)
    compute_payslip(regularization, dependents=dependents)
    _mark_regularization_computed(regularization, user)
    post_message(regularization, author=user, body=reason, is_note=True)
    return regularization
