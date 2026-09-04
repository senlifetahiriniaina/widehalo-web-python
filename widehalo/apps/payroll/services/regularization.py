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

Portée assumée et disclosée : ce service recopie et RECALCULE les
valeurs de l'original (reflétant par ex. une correction de présence
saisie après coup pour les mêmes dates) plutôt que de ne calculer qu'un
DELTA entre l'ancien et le nouveau montant — le rapprochement du delta
avec ce qui a déjà été effectivement payé reste à la charge du
gestionnaire de paie (hors périmètre de ce sprint, 4 JT)."""

from __future__ import annotations

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
