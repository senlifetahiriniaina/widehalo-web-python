"""Cascade OKR (`StgObjective`/`StgKeyResult`/`StgCheckIn`) — creation,
progression, et calcul automatique du statut (cf. docstring `models.py` :
`status` n'est jamais un cycle de vie pilote par l'utilisateur)."""

from __future__ import annotations

import importlib
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.strategy.models import StgCheckIn, StgKeyResult, StgObjective

if TYPE_CHECKING:
    from apps.core.models.tenant import Tenant
    from apps.core.models.user import User

# Seuil de progression moyenne au-dela duquel un objectif est considere
# "en bonne voie" plutot que "a risque" — decision de conception PRISE ICI
# (non specifiee explicitement au cadrage, disclosed) : 70% est un seuil
# usuel de pilotage OKR (methode Google/Doerr, "0.7 est un bon score"),
# retenu par coherence avec cette pratique plutot qu'invente arbitrairement.
_ON_TRACK_THRESHOLD_PCT = Decimal(70)


def create_objective(
    tenant: Tenant,
    *,
    title: str,
    level: str,
    period_start: Any,
    period_end: Any,
    description: str = "",
    owner: User | None = None,
    parent: StgObjective | None = None,
    department_id: Any = None,
    sector_code: str | None = None,
    created_by: User | None = None,
) -> StgObjective:
    """Cascade OKR (decision actee) : un objectif ne peut avoir pour parent
    qu'un objectif de niveau EGAL OU SUPERIEUR dans la hierarchie
    entreprise -> departement -> individuel (jamais un individuel comme
    parent d'un objectif d'entreprise)."""
    if (
        parent is not None
        and StgObjective.LEVEL_ORDER[parent.level] > StgObjective.LEVEL_ORDER[level]
    ):
        raise ValidationError(
            _(
                "Un objectif de niveau %(level)s ne peut pas avoir pour parent un "
                "objectif de niveau inferieur (%(parent_level)s)."
            )
            % {"level": level, "parent_level": parent.level}
        )
    objective = StgObjective(
        tenant=tenant,
        title=title,
        description=description,
        level=level,
        owner=owner,
        parent=parent,
        department_id=department_id,
        sector_code=sector_code or "",
        period_start=period_start,
        period_end=period_end,
        created_by=created_by,
        updated_by=created_by,
    )
    objective.full_clean()
    objective.save()
    return objective


def add_key_result(
    objective: StgObjective,
    *,
    metric_name: str,
    target_value: Decimal,
    unit: str = "",
    current_value: Decimal = Decimal(0),
    metric_code: str = "",
    kpi_source_module: str = "",
    kpi_source_function: str = "",
) -> StgKeyResult:
    """`metric_code` (cahier §13.3, STR-1) : quand fourni, DOIT référencer
    un indicateur PUBLIÉ du dictionnaire gouverné (`apps.analytics.
    AnMetricDefinition`) — validé ici, jamais un code inventé. Un résultat
    clé sans `metric_code` ni `kpi_source_module`/`kpi_source_function`
    reste possible (compatibilité ascendante) mais ne compte PAS pour la
    condition d'activation STR-1 (cf. `activate_objective`)."""
    if metric_code:
        from apps.analytics.services.public import get_metric_definition

        metric = get_metric_definition(objective.tenant, metric_code)
        if metric is None or metric["statut"] != "publie":
            raise ValidationError(
                _("Code indicateur inconnu ou non publié dans le dictionnaire : %(code)s")
                % {"code": metric_code}
            )
    key_result = StgKeyResult(
        tenant=objective.tenant,
        objective=objective,
        metric_name=metric_name,
        target_value=target_value,
        current_value=current_value,
        unit=unit,
        metric_code=metric_code,
        kpi_source_module=kpi_source_module,
        kpi_source_function=kpi_source_function,
    )
    key_result.full_clean()
    key_result.save()
    recompute_objective_status(objective)
    return key_result


def activate_objective(objective: StgObjective) -> StgObjective:
    """STR-1 : « la création d'un objectif SANS indicateur mesurable est
    refusée. » Le cycle `create_objective`/`add_key_result` reste en 2
    temps (compatibilité ascendante avec le modèle déjà livré) : c'est
    donc CETTE fonction, appelée explicitement par l'utilisateur avant de
    considérer un objectif comme officiellement suivi, qui porte la
    contrainte STR-1 — jamais `create_objective` seul (un objectif
    fraîchement créé, sans résultat clé, reste un brouillon légitime le
    temps de sa construction).

    **N'effectue AUCUNE transition manuelle de `status`** (porte de
    validation pure, lève `ValidationError` ou ne fait rien) : `status`
    reste TOUJOURS un champ calculé par `recompute_objective_status`,
    jamais un cycle de vie piloté par l'utilisateur (cf. docstring de tête
    de `models.py`) — et `recompute_objective_status` a de toute façon déjà
    fait sortir l'objectif de `STATUS_DRAFT` dès l'ajout du résultat clé
    qui satisfait la condition ci-dessous (`add_key_result` l'appelle),
    donc une transition `DRAFT -> ACTIVE` ici serait un code mort qui ne
    s'exécuterait jamais."""
    has_measurable_key_result = (
        objective.key_results.filter(is_active=True).exclude(metric_code="").exists()
    )
    if not has_measurable_key_result:
        raise ValidationError(
            _(
                "Un objectif sans résultat clé adossé à un indicateur du dictionnaire "
                "ne peut pas être activé."
            )
        )
    return objective


def compute_cascade_contribution(objective: StgObjective) -> list[dict[str, Any]]:
    """STR-2 : « la cascade affiche la contribution de chaque niveau au
    niveau supérieur et consolide l'avancement sans double comptage. »
    Retourne le chemin racine -> `objective` (inclus), une entrée par
    niveau, `contribution_pct` = progression PROPRE de ce niveau (jamais
    la moyenne des enfants, qui compterait deux fois la même donnée si un
    enfant a lui-même des enfants — la consolidation reste donc
    STRICTEMENT verticale, un niveau ne voit que sa propre progression et
    celle de son parent direct, jamais un agrégat transversal de tous ses
    descendants)."""
    chain: list[StgObjective] = []
    current: StgObjective | None = objective
    while current is not None:
        chain.append(current)
        current = current.parent
    chain.reverse()

    key_results_cache: dict[Any, list[StgKeyResult]] = {
        obj.id: list(obj.key_results.filter(is_active=True)) for obj in chain
    }

    def _progress(obj: StgObjective) -> Decimal:
        key_results = key_results_cache[obj.id]
        if not key_results:
            return Decimal(0)
        return sum((kr.progress_pct() for kr in key_results), Decimal(0)) / len(key_results)

    return [
        {
            "objective_id": obj.id,
            "title": obj.title,
            "level": obj.level,
            "own_progress_pct": _progress(obj),
        }
        for obj in chain
    ]


def record_check_in(
    key_result: StgKeyResult,
    *,
    date: Any,
    value: Decimal,
    comment: str = "",
    author: User | None = None,
) -> StgCheckIn:
    """`StgCheckIn` est la source de verite PAR DEFAUT de la progression :
    un check-in manuel met a jour `key_result.current_value` immediatement
    (contrairement a `refresh_key_result_from_source`, qui reste a la
    demande explicite de l'utilisateur)."""
    check_in = StgCheckIn(
        tenant=key_result.tenant,
        key_result=key_result,
        date=date,
        value=value,
        comment=comment,
        author=author,
    )
    check_in.full_clean()
    check_in.save()
    key_result.current_value = value
    key_result.full_clean()
    key_result.save(update_fields=["current_value", "updated_at"])
    recompute_objective_status(key_result.objective)
    return check_in


def recompute_objective_status(objective: StgObjective) -> str:
    """Statut calcule (jamais un workflow FSM, cf. `models.py`) :
    - aucun key result actif -> `draft` ;
    - progression moyenne >= 100% -> `achieved` ;
    - periode terminee (`period_end` depassee) et progression < 100% ->
      `missed` ;
    - progression moyenne >= `_ON_TRACK_THRESHOLD_PCT` -> `on_track` ;
    - sinon -> `at_risk`.

    Seuils/branchement DECIDES ICI (non specifies au cadrage, disclosed) —
    coherents avec la pratique OKR usuelle, pas une exigence explicite du
    plan."""
    key_results = list(objective.key_results.filter(is_active=True))
    if not key_results:
        status = StgObjective.STATUS_DRAFT
    else:
        average_progress = sum(
            (key_result.progress_pct() for key_result in key_results), Decimal(0)
        ) / len(key_results)
        today = timezone.now().date()
        if average_progress >= Decimal(100):
            status = StgObjective.STATUS_ACHIEVED
        elif objective.period_end < today:
            status = StgObjective.STATUS_MISSED
        elif average_progress >= _ON_TRACK_THRESHOLD_PCT:
            status = StgObjective.STATUS_ON_TRACK
        else:
            status = StgObjective.STATUS_AT_RISK

    if status != objective.status:
        objective.status = status
        objective.save(update_fields=["status", "updated_at"])
    return status


def refresh_key_result_from_source(tenant: Tenant, key_result: StgKeyResult) -> StgKeyResult:
    """Rafraichissement de `current_value` A LA DEMANDE uniquement — jamais
    un abonnement au bus d'evenements temps reel (simplification assumee et
    disclosed, cf. `models.py`/plan).

    **Convention d'appel decidee ici** (non specifiee au cadrage) : la
    fonction nommee par `kpi_source_function`, dans
    `apps.<kpi_source_module>.services.public`, doit accepter UNIQUEMENT
    `tenant` en argument positionnel et renvoyer une valeur coercible en
    `Decimal`, ou `None` si aucune donnee n'est disponible pour l'instant.
    Une source qui ne respecte pas cette convention (mauvais nom de module/
    fonction, signature differente) leve une `ValidationError` explicite,
    jamais un echec silencieux."""
    if not key_result.kpi_source_module or not key_result.kpi_source_function:
        raise ValidationError(_("Aucune source KPI configurée pour cet indicateur."))
    try:
        module = importlib.import_module(f"apps.{key_result.kpi_source_module}.services.public")
    except ImportError as exc:
        raise ValidationError(
            _("Module source KPI introuvable : %(module)s")
            % {"module": key_result.kpi_source_module}
        ) from exc
    function = getattr(module, key_result.kpi_source_function, None)
    if function is None or not callable(function):
        raise ValidationError(
            _("Fonction source KPI introuvable : %(function)s")
            % {"function": key_result.kpi_source_function}
        )
    raw_value = function(tenant)
    if raw_value is None:
        raise ValidationError(_("Aucune valeur disponible pour cette source KPI pour l'instant."))
    key_result.current_value = Decimal(str(raw_value))
    key_result.full_clean()
    key_result.save(update_fields=["current_value", "updated_at"])
    recompute_objective_status(key_result.objective)
    return key_result


def refresh_key_result_from_dictionary(
    tenant: Tenant, key_result: StgKeyResult, *, user: User
) -> StgKeyResult:
    """STR-1 : « l'avancement est calculé depuis l'indicateur, jamais saisi
    à la main. » Chemin PRÉFÉRÉ pour un résultat clé adossé au dictionnaire
    gouverné (`metric_code` renseigné) — passe par `bi.services.public.
    get_metric_current_value` (mêmes droits/garde-fous que le module BI,
    §13.1), jamais par le mécanisme `kpi_source_module`/`kpi_source_function`
    antérieur (conservé uniquement pour compatibilité ascendante, cf.
    `refresh_key_result_from_source`)."""
    if not key_result.metric_code:
        raise ValidationError(_("Ce résultat clé n'est adossé à aucun indicateur du dictionnaire."))
    from apps.bi.services.public import get_metric_current_value

    value = get_metric_current_value(tenant, key_result.metric_code, user)
    if value is None:
        raise ValidationError(
            _("Aucune valeur disponible pour l'indicateur %(code)s pour l'instant.")
            % {"code": key_result.metric_code}
        )
    key_result.current_value = value
    key_result.full_clean()
    key_result.save(update_fields=["current_value", "updated_at"])
    recompute_objective_status(key_result.objective)
    return key_result
